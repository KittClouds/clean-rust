import { Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
    TtsService,
    TTS_VOICES,
    type TTSEngine,
    type TtsVoice,
} from '../../../services/tts.service';

@Component({
    selector: 'app-tts-settings-popup',
    standalone: true,
    imports: [CommonModule],
    template: `
    <div class="relative">
        <!-- Settings Cog Button -->
        <button (click)="togglePopup()"
                class="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 focus:outline-none"
                [class.text-teal-500]="isOpen" [class.dark:text-teal-400]="isOpen"
                title="TTS Settings">
            <i class="pi pi-cog text-[10px]"></i>
        </button>

        <!-- Popup Card -->
        @if (isOpen) {
            <div class="absolute bottom-10 left-0 w-[25rem] bg-zinc-900 border border-teal-900/50 rounded-xl shadow-2xl z-50 overflow-hidden text-slate-300">
                <!-- Header -->
                <div class="px-4 py-3 bg-zinc-950 border-b border-white/5 flex items-center justify-between">
                    <span class="text-xs font-semibold text-teal-400 flex items-center gap-2">
                        <i class="pi pi-volume-up text-xs"></i>
                        TTS Settings
                    </span>
                    <button (click)="togglePopup()" class="text-slate-500 hover:text-slate-300 transition-colors">
                        <i class="pi pi-times text-xs"></i>
                    </button>
                </div>

                <!-- Content -->
                <div class="p-4 space-y-5">
                    <!-- Engine -->
                    <div>
                        <label class="text-[10px] text-slate-500 font-bold uppercase tracking-wider mb-2 block">Engine</label>
                        <div class="grid grid-cols-3 gap-2">
                            <button
                                (click)="selectEngine('browserSupertonic')"
                                class="px-3 py-2 text-[11px] rounded-lg border transition-all flex items-center justify-center gap-1.5"
                                [class.bg-teal-500/10]="ttsService.selectedEngine() === 'browserSupertonic'"
                                [class.border-teal-500/50]="ttsService.selectedEngine() === 'browserSupertonic'"
                                [class.text-teal-400]="ttsService.selectedEngine() === 'browserSupertonic'"
                                [class.bg-slate-800]="ttsService.selectedEngine() !== 'browserSupertonic'"
                                [class.border-transparent]="ttsService.selectedEngine() !== 'browserSupertonic'"
                                [class.text-slate-400]="ttsService.selectedEngine() !== 'browserSupertonic'">
                                <i class="pi pi-globe text-[9px]"></i>
                                <span class="font-medium">Web</span>
                            </button>
                            <button
                                (click)="selectEngine('nativeQwenClone')"
                                class="px-3 py-2 text-[11px] rounded-lg border transition-all flex items-center justify-center gap-1.5"
                                [class.bg-teal-500/10]="ttsService.selectedEngine() === 'nativeQwenClone'"
                                [class.border-teal-500/50]="ttsService.selectedEngine() === 'nativeQwenClone'"
                                [class.text-teal-400]="ttsService.selectedEngine() === 'nativeQwenClone'"
                                [class.bg-slate-800]="ttsService.selectedEngine() !== 'nativeQwenClone'"
                                [class.border-transparent]="ttsService.selectedEngine() !== 'nativeQwenClone'"
                                [class.text-slate-400]="ttsService.selectedEngine() !== 'nativeQwenClone'"
                                [disabled]="!ttsService.nativeAvailable() || !ttsService.nativeQwenCloneAvailable()"
                                [class.opacity-40]="!ttsService.nativeAvailable() || !ttsService.nativeQwenCloneAvailable()"
                                title="Qwen3-TTS 0.6B voice clone">
                                <i class="pi pi-sparkles text-[9px]"></i>
                                <span class="font-medium">Qwen</span>
                            </button>
                            <button
                                (click)="selectEngine('nativeSupertonicRust')"
                                class="px-3 py-2 text-[11px] rounded-lg border transition-all flex items-center justify-center gap-1.5"
                                [class.bg-teal-500/10]="ttsService.selectedEngine() === 'nativeSupertonicRust'"
                                [class.border-teal-500/50]="ttsService.selectedEngine() === 'nativeSupertonicRust'"
                                [class.text-teal-400]="ttsService.selectedEngine() === 'nativeSupertonicRust'"
                                [class.bg-slate-800]="ttsService.selectedEngine() !== 'nativeSupertonicRust'"
                                [class.border-transparent]="ttsService.selectedEngine() !== 'nativeSupertonicRust'"
                                [class.text-slate-400]="ttsService.selectedEngine() !== 'nativeSupertonicRust'"
                                [disabled]="!ttsService.nativeAvailable() || !ttsService.nativeSupertonicRustAvailable()"
                                [class.opacity-40]="!ttsService.nativeAvailable() || !ttsService.nativeSupertonicRustAvailable()"
                                title="Native Supertonic 3 Rust runner">
                                <i class="pi pi-bolt text-[9px]"></i>
                                <span class="font-medium">S3 Rust</span>
                            </button>
                        </div>
                    </div>

                    <!-- Voice Selection -->
                    <div>
                        <label class="text-[10px] text-slate-500 font-bold uppercase tracking-wider mb-2 block">
                            {{ ttsService.selectedEngine() === 'nativeQwenClone' ? 'Clone Source' : 'Voice' }}
                        </label>
                        @if (ttsService.selectedEngine() === 'nativeQwenClone') {
                            <div class="space-y-3 rounded-lg border border-teal-500/20 bg-teal-500/5 p-3 text-[11px] text-slate-300">
                                <div class="flex items-center justify-between gap-3">
                                    <div>
                                        <div class="font-semibold text-teal-300">Qwen3-TTS 0.6B Base</div>
                                        <div class="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-slate-500">{{ qwenModeLabel() }}</div>
                                    </div>
                                    <button
                                        (click)="toggleQwenPromptCache()"
                                        class="rounded-md border px-2 py-1 text-[10px] font-bold uppercase tracking-wider transition-colors"
                                        [class.border-teal-500/40]="ttsService.qwenCloneUsePromptCache()"
                                        [class.bg-teal-500/10]="ttsService.qwenCloneUsePromptCache()"
                                        [class.text-teal-300]="ttsService.qwenCloneUsePromptCache()"
                                        [class.border-slate-700]="!ttsService.qwenCloneUsePromptCache()"
                                        [class.bg-slate-900]="!ttsService.qwenCloneUsePromptCache()"
                                        [class.text-slate-500]="!ttsService.qwenCloneUsePromptCache()">
                                        Cache
                                    </button>
                                </div>

                                <label class="block">
                                    <span class="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Reference WAV</span>
                                    <input
                                        class="w-full rounded-md border border-white/10 bg-zinc-950 px-2 py-1.5 text-[11px] text-slate-200 outline-none transition-colors focus:border-teal-500/50"
                                        [value]="ttsService.qwenCloneReferenceAudio()"
                                        (input)="setQwenReferenceAudio($event)"
                                        spellcheck="false" />
                                </label>

                                <label class="block">
                                    <span class="mb-1 flex items-center justify-between gap-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                        <span>Transcript</span>
                                        <button
                                            type="button"
                                            (click)="useSelectionAsQwenTranscript()"
                                            class="text-teal-400 hover:text-teal-300">
                                            Use selection
                                        </button>
                                    </span>
                                    <textarea
                                        rows="3"
                                        class="w-full resize-none rounded-md border border-white/10 bg-zinc-950 px-2 py-1.5 text-[11px] text-slate-200 outline-none transition-colors focus:border-teal-500/50"
                                        [value]="ttsService.qwenCloneReferenceText()"
                                        (input)="setQwenReferenceText($event)"
                                        spellcheck="false"></textarea>
                                </label>

                                <label class="block">
                                    <span class="mb-1 flex items-center justify-between gap-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                        <span>Prompt Cache</span>
                                        <button
                                            type="button"
                                            (click)="createFreshQwenPromptCache()"
                                            class="text-teal-400 hover:text-teal-300">
                                            New prompt
                                        </button>
                                    </span>
                                    <input
                                        class="w-full rounded-md border border-white/10 bg-zinc-950 px-2 py-1.5 text-[11px] text-slate-200 outline-none transition-colors focus:border-teal-500/50"
                                        [value]="ttsService.qwenClonePromptPath()"
                                        (input)="setQwenPromptPath($event)"
                                        spellcheck="false" />
                                </label>
                            </div>
                        } @else {
                        <div class="grid grid-cols-2 gap-2">
                            @for (voice of voices; track voice.id) {
                                <button 
                                    (click)="selectVoice(voice)"
                                    class="px-3 py-2 text-[11px] rounded-lg border transition-all flex items-center justify-center gap-1.5"
                                    [class.bg-teal-500/10]="ttsService.selectedVoice().id === voice.id"
                                    [class.border-teal-500/50]="ttsService.selectedVoice().id === voice.id"
                                    [class.text-teal-400]="ttsService.selectedVoice().id === voice.id"
                                    [class.bg-slate-800]="ttsService.selectedVoice().id !== voice.id"
                                    [class.border-transparent]="ttsService.selectedVoice().id !== voice.id"
                                    [class.text-slate-400]="ttsService.selectedVoice().id !== voice.id"
                                    [class.hover:bg-slate-700]="ttsService.selectedVoice().id !== voice.id">
                                    <i class="pi text-[9px]" 
                                       [class.pi-user]="voice.gender === 'male'"
                                       [class.pi-heart]="voice.gender === 'female'"></i>
                                    <span class="font-medium">{{ voice.name }}</span>
                                </button>
                            }
                        </div>
                        }
                    </div>

                    <!-- Model Status & Load Button -->
                    <div class="pt-4 border-t border-white/5 flex items-center justify-between">
                        <div class="flex flex-col">
                            <span class="text-[10px] text-slate-500 font-bold uppercase tracking-wider mb-1">Model Status</span>
                            <span class="flex items-center gap-1.5 text-[11px] font-medium"
                                  [class.text-teal-400]="ttsService.modelState() === 'ready'"
                                  [class.text-amber-400]="ttsService.modelState() === 'loading'"
                                  [class.text-red-400]="ttsService.modelState() === 'error'"
                                  [class.text-slate-400]="ttsService.modelState() === 'idle'">
                                <i class="pi text-[10px]"
                                   [class.pi-check-circle]="ttsService.modelState() === 'ready'"
                                   [class.pi-spin]="ttsService.modelState() === 'loading'"
                                   [class.pi-spinner]="ttsService.modelState() === 'loading'"
                                   [class.pi-times-circle]="ttsService.modelState() === 'error'"
                                   [class.pi-circle]="ttsService.modelState() === 'idle'"></i>
                                {{ statusLabel() }}
                            </span>
                        </div>
                        
                        @if (ttsService.modelState() === 'idle' || ttsService.modelState() === 'error') {
                            <button (click)="loadModel()" 
                                    class="px-3 py-1.5 bg-teal-500/10 hover:bg-teal-500/20 border border-teal-500/30 text-teal-400 text-[10px] font-bold uppercase tracking-wider rounded-md transition-colors flex items-center gap-1.5 focus:outline-none">
                                <i class="pi pi-download text-[9px]"></i>
                                Load Engine
                            </button>
                        } @else if (ttsService.modelState() === 'loading') {
                            <div class="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[10px] font-bold uppercase tracking-wider rounded-md flex items-center gap-1.5">
                                <i class="pi pi-spin pi-spinner text-[9px]"></i>
                                Loading
                            </div>
                        } @else {
                            <button (click)="unloadModel()" 
                                    class="px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-500 text-[10px] font-bold uppercase tracking-wider rounded-md transition-colors flex items-center gap-1.5 focus:outline-none"
                                    title="Unload engine to free memory">
                                <i class="pi pi-eject text-[9px]"></i>
                                Unload
                            </button>
                        }
                    </div>
                </div>
            </div>
        }

        <!-- Backdrop to close -->
        @if (isOpen) {
            <div (click)="togglePopup()" class="fixed inset-0 z-40"></div>
        }
    </div>
  `,
    styles: [`
        :host { display: contents; }
    `]
})
export class TtsSettingsPopupComponent {
    ttsService = inject(TtsService);

    isOpen = false;
    voices = TTS_VOICES;

    togglePopup() {
        this.isOpen = !this.isOpen;
    }

    selectVoice(voice: TtsVoice) {
        this.ttsService.setVoice(voice);
    }

    selectEngine(engine: TTSEngine) {
        this.ttsService.setEngine(engine);
    }

    setQwenReferenceAudio(event: Event) {
        this.ttsService.setQwenCloneReferenceAudio(inputValue(event));
    }

    setQwenReferenceText(event: Event) {
        this.ttsService.setQwenCloneReferenceText(inputValue(event));
    }

    setQwenPromptPath(event: Event) {
        this.ttsService.setQwenClonePromptPath(inputValue(event));
    }

    toggleQwenPromptCache() {
        this.ttsService.setQwenCloneUsePromptCache(!this.ttsService.qwenCloneUsePromptCache());
    }

    createFreshQwenPromptCache() {
        this.ttsService.createFreshQwenPromptCache();
    }

    useSelectionAsQwenTranscript() {
        const selected = window.getSelection()?.toString().trim();
        if (selected) {
            this.ttsService.setQwenCloneReferenceText(selected);
        }
    }

    loadModel() {
        this.ttsService.loadModel();
    }

    unloadModel() {
        this.ttsService.unloadModel();
    }

    statusLabel = computed(() => {
        switch (this.ttsService.modelState()) {
            case 'ready':
                return 'Ready';
            case 'loading': return `${this.ttsService.loadProgress()}%`;
            case 'error': return 'Error';
            default: return 'Not Loaded';
        }
    });

    qwenModeLabel = computed(() => {
        switch (this.ttsService.qwenCloneMode()) {
            case 'prompt-cache':
                return 'Prompt cache';
            case 'icl':
                return 'Transcript clone';
            default:
                return 'X-vector clone';
        }
    });
}

function inputValue(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement | null)?.value ?? '';
}
