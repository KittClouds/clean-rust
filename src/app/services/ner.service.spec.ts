import { beforeEach, describe, expect, it, vi } from 'vitest';
import { signal } from '@angular/core';
import { readFileSync } from 'node:fs';

vi.mock('../lib/registry', () => ({
  smartGraphRegistry: {
    isRegisteredEntity: vi.fn(() => false),
    registerEntity: vi.fn(),
  },
}));

vi.mock('../lib/store/note-editor.store', () => ({
  NoteEditorStore: vi.fn(),
}));

vi.mock('../lib/dexie/settings.service', () => ({
  getSetting: vi.fn(() => null),
  setSetting: vi.fn(),
}));

vi.mock('../lib/entity-learning/entity-feedback', () => ({
  filterRejectedSuggestions: vi.fn(async (suggestions) => suggestions),
  recordSuggestionAccepted: vi.fn(async () => undefined),
  recordSuggestionRejected: vi.fn(async () => undefined),
}));

vi.mock('../graph-rebuild/entity-anchor-acceptance', () => ({
  recordAcceptedEntityAnchor: vi.fn(async () => undefined),
}));

vi.mock('uuid', () => ({
  v4: vi.fn(() => 'uuid-1'),
}));

import { smartGraphRegistry } from '../lib/registry';
import { recordAcceptedEntityAnchor } from '../graph-rebuild/entity-anchor-acceptance';
import { NerService } from './ner.service';

describe('NerService provider orchestration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function makeService() {
    return Object.assign(Object.create(NerService.prototype), {
      noteStore: {
        currentNote: vi.fn(() => ({ id: 'note-1', title: 'Untitled Note' })),
      },
      fstProvider: {
        scan: vi.fn(async () => []),
        getStatus: vi.fn(async () => ({ ready: true, loading: false, device: null })),
        dispose: vi.fn(async () => undefined),
      },
      lfmLocalProvider: {
        status: signal({ ready: false, loading: false, device: null }),
        scan: vi.fn(async () => []),
        getStatus: vi.fn(async () => ({ ready: true, loading: false, device: 'wasm' })),
        dispose: vi.fn(async () => undefined),
      },
      glinerLocalProvider: {
        status: signal({ ready: false, loading: false, device: null }),
        scan: vi.fn(async () => []),
        getStatus: vi.fn(async () => ({ ready: true, loading: false, device: 'wasm' })),
        dispose: vi.fn(async () => undefined),
      },
      suggestions: signal([]),
      fstEnabled: signal(true),
      fstStatus: signal({ ready: true, loading: false, device: null }),
      isAnalyzing: signal(false),
      activeProvider: signal(null),
      lastSuggestionSource: signal(null),
      errorMessage: signal(null),
      currentText: '',
    }) as NerService & {
      fstProvider: { scan: ReturnType<typeof vi.fn>; getStatus: ReturnType<typeof vi.fn> };
      lfmLocalProvider: {
        status: ReturnType<typeof signal>;
        scan: ReturnType<typeof vi.fn>;
        getStatus: ReturnType<typeof vi.fn>;
      };
    };
  }

  it('accepting a suggestion feeds Alex and writes an accepted graph anchor', async () => {
    vi.mocked(smartGraphRegistry.registerEntity).mockReturnValue({
      entity: {
        id: 'entity-kai',
        label: 'Kai',
        kind: 'CHARACTER',
        aliases: [],
        firstNote: 'note-1',
        mentionsByNote: new Map(),
        totalMentions: 1,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'user',
        registeredAt: 1,
      },
      isNew: true,
      wasMerged: false,
    } as any);
    const service = makeService();
    (service as any).currentText = 'Kai crossed the room.';
    service.suggestions.set([
      {
        id: 's-1',
        label: 'Kai',
        kind: 'CHARACTER',
        confidence: 0.91,
        source: 'dynamic_ner',
      },
    ] as any);

    await service.acceptSuggestion('s-1');

    expect(smartGraphRegistry.registerEntity).toHaveBeenCalledWith('Kai', 'CHARACTER', 'note-1', expect.objectContaining({
      source: 'user',
      attributes: expect.objectContaining({ discoverySource: 'dynamic_ner' }),
    }));
    expect(recordAcceptedEntityAnchor).toHaveBeenCalledWith(expect.objectContaining({
      noteId: 'note-1',
      surface: 'Kai',
      plainText: 'Kai crossed the room.',
      confidence: 0.91,
    }));
  });

  it('auto-accepted context suggestions register as extraction, not user curation', async () => {
    vi.mocked(smartGraphRegistry.registerEntity).mockReturnValue({
      entity: {
        id: 'entity-kai',
        label: 'Kai',
        kind: 'CHARACTER',
        aliases: [],
        firstNote: 'note-1',
        mentionsByNote: new Map(),
        totalMentions: 1,
        lastSeenDate: new Date(1),
        createdAt: new Date(1),
        createdBy: 'extraction',
        registeredAt: 1,
      },
      isNew: true,
      wasMerged: false,
    } as any);
    const service = makeService();
    service.suggestions.set([
      {
        id: 's-1',
        label: 'Kai',
        kind: 'CHARACTER',
        confidence: 0.91,
        source: 'dynamic_ner',
      },
    ] as any);

    await service.acceptSuggestionForContext('s-1', {
      noteId: 'note-1',
      plainText: 'Kai crossed the room.',
      registrationSource: 'extraction',
    });

    expect(smartGraphRegistry.registerEntity).toHaveBeenCalledWith('Kai', 'CHARACTER', 'note-1', expect.objectContaining({
      source: 'extraction',
    }));
  });

  it('analyzeNote still routes through the Phoenix scan provider', async () => {
    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Kai',
        kind: 'person',
        confidence: 'high',
        rawScore: 0.91,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
    ]);

    await service.analyzeNote('Kai crossed the room.');

    expect(service.fstProvider.scan).toHaveBeenCalledWith({
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: 'Kai crossed the room.',
    });
    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Kai',
        kind: 'CHARACTER',
        confidence: 0.91,
        source: 'dynamic_ner',
      }),
    ]);
  });

  it('runManualScan maps LFM suggestions into enhanced cards', async () => {
    const service = makeService();
    service.lfmLocalProvider.scan.mockResolvedValue([
      {
        label: 'Fiora',
        kind: 'PERSON',
        confidence: 'high',
        reasoning: 'Named speaker with repeated evidence.',
        evidence: 'Fiora smiles without shame.',
        aliases: ['Lady Fiora'],
      },
    ]);

    await service.runManualScan('lfm_local_experiment', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: 'Fiora smiles without shame.',
    });

    expect(service.lfmLocalProvider.scan).toHaveBeenCalledWith({
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: 'Fiora smiles without shame.',
    });
    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Fiora',
        kind: 'CHARACTER',
        confidence: 0.9,
        context: 'Fiora smiles without shame.',
        llmEnhanced: true,
        llmReasoning: 'Named speaker with repeated evidence.',
        source: 'lfm_local_experiment',
      }),
    ]);
    expect(service.lastSuggestionSource()).toBe('lfm_local_experiment');
  });

  it('keeps prior suggestions when the local model scan fails', async () => {
    const service = makeService();
    service.suggestions.set([
      {
        id: 'existing',
        label: 'Kai',
        kind: 'UNKNOWN',
        confidence: 0.8,
        source: 'fst',
      },
    ] as any);
    service.lastSuggestionSource.set('fst');
    service.lfmLocalProvider.scan.mockRejectedValue(new Error('Model output was invalid'));

    await service.runManualScan('lfm_local_experiment', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: 'Kai crossed the room.',
    });

    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Kai',
        source: 'fst',
      }),
    ]);
    expect(service.errorMessage()).toBe('Model output was invalid');
    expect(service.isAnalyzing()).toBe(false);
  });

  it('filters registered labels before exposing provider suggestions', async () => {
    vi.mocked(smartGraphRegistry.isRegisteredEntity).mockImplementation(
      (label: string) => label === 'Known',
    );

    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Known',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.7,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'Kai',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.7,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
    ]);

    await service.runManualScan('fst', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: 'Kai met Known.',
    });

    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Kai',
      }),
    ]);
  });

  it('keeps Phoenix scan suggestions behind stopword and character heuristics', async () => {
    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Above',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.78,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'All the',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.78,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'And',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.78,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'Already',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.78,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'Arcadia',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.78,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'Because',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.78,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'Kai',
        kind: 'CHARACTER',
        confidence: 'high',
        rawScore: 0.91,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
      {
        label: 'Tempiris',
        kind: 'CHARACTER',
        confidence: 'high',
        rawScore: 0.91,
        reasoning: '',
        evidence: '',
        aliases: [],
      },
    ]);

    await service.runManualScan('fst', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: [
        'Above the room, Kai watched. And then Kai laughed.',
        'Already the door moved. Because the room changed.',
        'Arcadia opened once. Arcadia closed once.',
        "Tempiris's smile widened.",
      ].join(' '),
    });

    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Kai',
        kind: 'CHARACTER',
        source: 'fst',
      }),
      expect.objectContaining({
        label: 'Tempiris',
        kind: 'CHARACTER',
        source: 'fst',
      }),
    ]);
  });

  it('honors broad model labels and generic role cues without story-name overrides', async () => {
    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Red Arcadia',
        kind: 'LOCATION',
        confidence: 'medium',
        rawScore: 0.62,
        reasoning: '',
        evidence: 'The Red Arcadia interior had settled around the Kharon Vel access.',
        aliases: [],
      },
      {
        label: 'Arcadia',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.62,
        reasoning: '',
        evidence: 'Arcadia had swallowed the transit seat.',
        aliases: [],
      },
      {
        label: 'Boundary Veir',
        kind: 'CONCEPT',
        confidence: 'medium',
        rawScore: 0.58,
        reasoning: '',
        evidence: "A full city's worth of Boundary Veir sat on the other side.",
        aliases: [],
      },
      {
        label: 'The Titan',
        kind: 'CREATURE',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'The Titan crossed the lane.',
        aliases: [],
      },
      {
        label: 'Titan guard',
        kind: 'CHARACTER',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'The Titan guard stood at the access.',
        aliases: [],
      },
      {
        label: 'dwarf',
        kind: 'UNKNOWN',
        confidence: 'low',
        rawScore: 0.46,
        reasoning: '',
        evidence: 'A dwarf yelled the same word three times.',
        aliases: [],
      },
      {
        label: 'devil boy',
        kind: 'UNKNOWN',
        confidence: 'low',
        rawScore: 0.45,
        reasoning: '',
        evidence: 'A devil boy with powdered sugar darted past.',
        aliases: [],
      },
    ]);

    await service.runManualScan('fst', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: [
        'The Red Arcadia interior had settled around the Kharon Vel access.',
        'Arcadia had swallowed the transit seat.',
        "A full city's worth of Boundary Veir sat on the other side.",
        'The Titan crossed the lane.',
        'The Titan guard stood at the access.',
        'A dwarf yelled the same word three times.',
        'A devil boy with powdered sugar darted past.',
      ].join(' '),
    });

    expect(service.suggestions()).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Red Arcadia', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Boundary Veir', kind: 'CONCEPT' }),
      expect.objectContaining({ label: 'The Titan', kind: 'CREATURE' }),
      expect.objectContaining({ label: 'Titan guard', kind: 'NPC' }),
      expect.objectContaining({ label: 'devil boy', kind: 'NPC' }),
    ]));
    expect(service.suggestions()).not.toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Arcadia', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'dwarf', kind: 'NPC' }),
    ]));
  });

  it('keeps provider kind stable and records location context as review evidence', async () => {
    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Germany',
        kind: 'CHARACTER',
        confidence: 'high',
        rawScore: 0.91,
        reasoning: '',
        evidence: "Germany's price is exchange.",
        aliases: [],
      },
      {
        label: 'Kai',
        kind: 'CHARACTER',
        confidence: 'high',
        rawScore: 0.91,
        reasoning: '',
        evidence: 'Kai said yes.',
        aliases: [],
      },
    ]);

    await service.runManualScan('fst', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: "Germany's price is exchange. Kai said yes.",
    });

    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Germany',
        kind: 'CHARACTER',
        requiresReview: true,
        reviewReason: 'location_context_conflict',
        kindVotes: expect.arrayContaining([
          expect.objectContaining({ kind: 'LOCATION', source: 'angular_location_context' }),
        ]),
      }),
      expect.objectContaining({
        label: 'Kai',
        kind: 'CHARACTER',
        requiresReview: false,
      }),
    ]);
  });

  it('surfaces story locations from native location context without collapsing people', async () => {
    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Baton Rouge',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.62,
        reasoning: '',
        evidence: 'Baton Rouge came first.',
        aliases: [],
      },
      {
        label: 'Lower Mississippi',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.61,
        reasoning: '',
        evidence: 'Baton Rouge. Lower Mississippi. Fuel movement. Rail breaks. River locks.',
        aliases: [],
      },
      {
        label: 'Redwater',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.58,
        reasoning: '',
        evidence: 'Clearing Redwater or Black Cypress if dungeon control is part of the break.',
        aliases: [],
      },
      {
        label: 'Black Cypress',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.58,
        reasoning: '',
        evidence: 'Clearing Redwater or Black Cypress if dungeon control is part of the break.',
        aliases: [],
      },
      {
        label: 'Blacktooth',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'Iriane had only just returned from Blacktooth.',
        aliases: [],
      },
      {
        label: 'Boundary Keep',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'Blacktooth now has Boundary Keep interference.',
        aliases: [],
      },
      {
        label: 'Skyglass',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'Skyglass has Aetherians and Kyodai.',
        aliases: [],
      },
      {
        label: 'Malachor',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'Malachor already has one tower.',
        aliases: [],
      },
      {
        label: 'Halcyon',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.57,
        reasoning: '',
        evidence: 'Soleya remained on a side pane from Halcyon.',
        aliases: [],
      },
      {
        label: 'Rook',
        kind: 'CHARACTER',
        confidence: 'high',
        rawScore: 0.86,
        reasoning: '',
        evidence: 'Rook said the answer aloud.',
        aliases: [],
      },
      {
        label: 'Allied Table',
        kind: 'ORGANIZATION',
        confidence: 'high',
        rawScore: 0.84,
        reasoning: '',
        evidence: 'Allied Table approved the operation.',
        aliases: [],
      },
    ]);

    await service.runManualScan('fst', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: [
        'Baton Rouge came first.',
        'Baton Rouge. Lower Mississippi. Fuel movement. Rail breaks. River locks.',
        'Clearing Redwater or Black Cypress if dungeon control is part of the break.',
        'Iriane had only just returned from Blacktooth.',
        'Blacktooth now has Boundary Keep interference.',
        'Skyglass has Aetherians and Kyodai.',
        'Malachor already has one tower.',
        'Soleya remained on a side pane from Halcyon.',
        'Rook said the answer aloud. Allied Table approved the operation.',
      ].join(' '),
    });

    expect(service.suggestions()).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Baton Rouge', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Lower Mississippi', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Redwater', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Black Cypress', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Blacktooth', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Boundary Keep', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Skyglass', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Malachor', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Halcyon', kind: 'LOCATION' }),
      expect.objectContaining({ label: 'Rook', kind: 'CHARACTER' }),
      expect.objectContaining({ label: 'Allied Table', kind: 'NETWORK' }),
    ]));
    expect(service.suggestions().find((suggestion) => suggestion.label === 'Rook')?.kind).not.toBe('LOCATION');
    expect(service.suggestions().find((suggestion) => suggestion.label === 'Allied Table')?.kind).not.toBe('LOCATION');
  });

  it('flattens group-like story entities into networks', async () => {
    const service = makeService();
    service.fstProvider.scan.mockResolvedValue([
      {
        label: 'Allied Table',
        kind: 'LOCATION',
        confidence: 'medium',
        rawScore: 0.64,
        reasoning: '',
        evidence: 'Allied Table approved Red Mesa.',
        aliases: [],
      },
      {
        label: 'Atlas',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.62,
        reasoning: '',
        evidence: 'Atlas backing. Nemo and Nereus in the line.',
        aliases: [],
      },
      {
        label: 'Joint Chiefs',
        kind: 'ORGANIZATION',
        confidence: 'medium',
        rawScore: 0.62,
        reasoning: '',
        evidence: 'Joint Chiefs, Nemo, Atlas, Allied Table.',
        aliases: [],
      },
      {
        label: 'militia',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.5,
        reasoning: '',
        evidence: 'Local militia hero.',
        aliases: [],
      },
      {
        label: 'military',
        kind: 'UNKNOWN',
        confidence: 'medium',
        rawScore: 0.5,
        reasoning: '',
        evidence: 'Rook is a military officer.',
        aliases: [],
      },
    ]);

    await service.runManualScan('fst', {
      noteId: 'note-1',
      noteTitle: 'Untitled Note',
      plainText: [
        'Allied Table approved Red Mesa.',
        'Atlas backing. Joint Chiefs, Nemo, Atlas, Allied Table.',
        'Local militia hero. Rook is a military officer.',
      ].join(' '),
    });

    expect(service.suggestions()).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: 'Allied Table', kind: 'NETWORK' }),
      expect.objectContaining({ label: 'Atlas', kind: 'NETWORK' }),
      expect.objectContaining({ label: 'Joint Chiefs', kind: 'NETWORK' }),
      expect.objectContaining({ label: 'militia', kind: 'NETWORK' }),
      expect.objectContaining({ label: 'military', kind: 'NETWORK' }),
    ]));
  });

  it('applies the same Phoenix gate to Atlas surface suggestions', async () => {
    const service = makeService();

    await service.loadAtlasSurfaceSuggestions([
      {
        id: 'bad-1',
        label: 'Absolutely',
        kind: 'CHARACTER',
        confidence: 0.78,
        evidence: 'Absolutely not.',
        sourceStage: 'dynamicNer',
      },
      {
        id: 'bad-2',
        label: 'All of',
        kind: 'CHARACTER',
        confidence: 0.78,
        evidence: 'All of them stayed quiet.',
        sourceStage: 'dynamicNer',
      },
      {
        id: 'good-1',
        label: 'Kai',
        kind: 'CHARACTER',
        confidence: 0.91,
        evidence: 'Kai watched. Kai laughed.',
        sourceStage: 'dynamicNer',
      },
    ] as any);

    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Kai',
        kind: 'CHARACTER',
        source: 'atlas_surface',
      }),
    ]);
  });

  it('honors native kind votes for Atlas suggestions and marks low confidence as review-only', async () => {
    const service = makeService();

    await service.loadAtlasSurfaceSuggestions([
      {
        id: 'org-1',
        label: 'Allied Table',
        kind: 'ORGANIZATION',
        confidence: 0.82,
        evidence: 'Allied Table approved the Red Mesa route.',
        sourceStage: 'dynamicNer',
        kindVotes: [
          { kind: 'ORGANIZATION', source: 'model_discovery', confidence: 0.82, reason: 'ModelLabel' },
          { kind: 'LOCATION', source: 'model_discovery', confidence: 0.18, reason: 'context' },
        ],
        decisionStatus: 'accepted',
      },
      {
        id: 'low-1',
        label: 'Allied Table city',
        kind: 'LOCATION',
        confidence: 0.07,
        evidence: 'Allied Table city',
        sourceStage: 'dynamicNer',
        decisionStatus: 'review',
      },
    ] as any);

    expect(service.suggestions()).toEqual([
      expect.objectContaining({
        label: 'Allied Table',
        kind: 'NETWORK',
        requiresReview: false,
        kindVotes: expect.arrayContaining([
          expect.objectContaining({ kind: 'NETWORK', source: 'model_discovery' }),
        ]),
      }),
      expect.objectContaining({
        label: 'Allied Table city',
        kind: 'LOCATION',
        requiresReview: true,
        decisionStatus: 'review',
      }),
    ]);
  });

  it('smokes Angular arbitration over shortrun and mother2 genre samples', async () => {
    const service = makeService();
    const shortrun = readFileSync(new URL('../../../docs/shortrun.md', import.meta.url), 'utf8');
    const mother2 = readFileSync(new URL('../../../docs/mother2.md', import.meta.url), 'utf8');

    await service.loadAtlasSurfaceSuggestions([
      {
        id: 'control-org',
        label: 'Allied Table',
        kind: 'ORGANIZATION',
        confidence: 0.86,
        evidence: `${shortrun.slice(0, 1200)} Allied Table approved Red Mesa.`,
        sourceStage: 'dynamicNer',
        kindVotes: [
          { kind: 'ORGANIZATION', source: 'model_discovery', confidence: 0.86, reason: 'ModelLabel' },
        ],
        decisionStatus: 'accepted',
      },
      {
        id: 'control-location',
        label: 'Red Mesa',
        kind: 'LOCATION',
        confidence: 0.62,
        evidence: `${shortrun.slice(0, 1200)} Allied Table approved Red Mesa.`,
        sourceStage: 'dynamicNer',
        kindVotes: [
          { kind: 'LOCATION', source: 'native_location_shape', confidence: 0.46, reason: 'location_surface_or_context' },
        ],
        decisionStatus: 'review',
      },
      {
        id: 'variable-person',
        label: 'Rook',
        kind: 'CHARACTER',
        confidence: 0.81,
        evidence: `${mother2.slice(0, 1200)} Rook said the answer aloud.`,
        sourceStage: 'dynamicNer',
        kindVotes: [
          { kind: 'CHARACTER', source: 'model_discovery', confidence: 0.81, reason: 'ModelLabel' },
        ],
        decisionStatus: 'accepted',
      },
    ] as any);

    expect(service.suggestions()).toEqual([
      expect.objectContaining({ label: 'Allied Table', kind: 'NETWORK', requiresReview: false }),
      expect.objectContaining({ label: 'Red Mesa', kind: 'LOCATION', requiresReview: true }),
      expect.objectContaining({ label: 'Rook', kind: 'CHARACTER', requiresReview: false }),
    ]);
    expect(service.suggestions().find((suggestion) => suggestion.label === 'Rook')?.kind).not.toBe('LOCATION');
    expect(service.suggestions().find((suggestion) => suggestion.label === 'Allied Table')?.kind).not.toBe('LOCATION');
  });
});
