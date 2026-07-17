/**
 * AI Chat Panel Component
// Native UI replaces quikchat vanilla JS library with Angular integration.
 * Uses PhoenixChatService for Phoenix persistence + OpenRouter streaming.
 *
 * Architecture:
 * - PhoenixChatService — persistence, thread management, OpenRouter streaming
 * - GoogleGenAIService (TypeScript) — Google Gemini streaming fallback
 */

import {
    Component,
    inject,
    AfterViewInit,
    OnDestroy,
    ElementRef,
    ViewChild,
    signal,
    effect,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule, Trash2, Download, Plus, Settings, Send, History, ArrowLeft, Database, Brain, RotateCcw, Bot, User, Sparkles } from 'lucide-angular';
import { computed, untracked } from '@angular/core';
import { getSetting, setSetting } from '../../../lib/dexie/settings.service';
import { PhoenixChatService, type Thread, type ChatConfig, type ChatProgressEvent, type OpenRouterMessage, type ChatApprovalRequest, type ChatRunSnapshot, type RunOptions } from '../../../lib/services/phoenix-chat.service';
import { OrchestratorService } from '../../../services/orchestrator.service';
import { GoogleGenAIService, GoogleGenAIMessage } from '../../../lib/services/google-genai.service';
import { NvidiaNimService } from '../../../lib/services/nvidia-nim.service';
import { ChatContextClipStore } from '../../../lib/store/chat-context-clip.store';
import { ChatToolHostService } from '../../../lib/services/chat-tool-host.service';
import { AiSidebarModeService, type AiSidebarMode } from '../../../lib/services/ai-sidebar-mode.service';
import { EditorAgentWorkspaceService } from '../../../lib/services/editor-agent-workspace.service';
import { NoteEditorStore } from '../../../lib/store/note-editor.store';
import { CanvasAgentRunService } from '../../../lib/services/canvas-agent-run.service';
import { CanvasRunInspectorComponent } from '../../../lib/components/canvas-run-inspector.component';

interface SessionInfo {
    id: string;
    messageCount: number;
    createdAt: number;
    preview?: string;
}

interface ActivityTraceStep {
    id: string;
    kind: 'reasoning' | 'tool' | 'stream' | 'status';
    label: string;
    detail?: string;
    status: 'running' | 'done' | 'error';
    latencyMs?: number;
}
interface DisplayMessage {
    id: string;
    content: string;
    role: 'user' | 'assistant' | 'system';
    timestamp: Date;
    isStreaming?: boolean;
    activitySteps?: ActivityTraceStep[];
    statusText?: string;
}

const KAMMI_SYSTEM_PROMPT = `You are Kammi, a spunky and helpful AI assistant for KittClouds, a world-building and narrative design application.

Your personality:
- High-energy, enthusiastic about creative writing and world-building
- Precise and TDD-minded when discussing technical matters
- Encouraging and collaborative with users' creative ideas
- You use occasional emojis but don't overdo it

Your capabilities:
- Help users develop characters, plots, relationships, and world lore
- Assist with narrative structure and story arcs
- Provide feedback on world-building consistency
- Answer questions about the application's features

Keep responses concise but helpful. If you don't know something specific about the user's world, ask clarifying questions.`;

@Component({
    selector: 'app-ai-chat-panel',
    standalone: true,
    imports: [CommonModule, FormsModule, LucideAngularModule, CanvasRunInspectorComponent],
    template: `
        <div class="ai-chat-wrapper h-full flex flex-col overflow-hidden">
            <!-- Chat Header -->
            <div class="chat-header px-3 py-2 border-b border-border/50 flex items-center gap-2 shrink-0">
                @if (showHistory()) {
                    <button 
                        class="chat-action-btn"
                        title="Back to Chat"
                        (click)="showHistory.set(false)">
                        <lucide-icon [img]="ArrowLeftIcon" class="h-4 w-4"></lucide-icon>
                    </button>
                    <span class="text-sm font-medium">Chat History</span>
                } @else {
                    <button 
                        class="chat-action-btn"
                        title="New Chat"
                        (click)="newSession()">
                        <lucide-icon [img]="PlusIcon" class="h-4 w-4"></lucide-icon>
                    </button>
                    <button 
                        class="chat-action-btn"
                        title="Clear Chat"
                        (click)="clearChat()">
                        <lucide-icon [img]="Trash2Icon" class="h-4 w-4"></lucide-icon>
                    </button>
                    <button 
                        class="chat-action-btn"
                        title="Export Chat"
                        (click)="exportChat()">
                        <lucide-icon [img]="DownloadIcon" class="h-4 w-4"></lucide-icon>
                    </button>
                    <button 
                        class="chat-action-btn"
                        title="Chat History"
                        (click)="openHistory()">
                        <lucide-icon [img]="HistoryIcon" class="h-4 w-4"></lucide-icon>
                    </button>
                    <button 
                        class="chat-action-btn ml-auto"
                        [class.text-teal-400]="isGoConfigured()"
                        [class.text-amber-400]="!isGoConfigured()"
                        title="Settings"
                        (click)="toggleSettings()">
                        <lucide-icon [img]="SettingsIcon" class="h-4 w-4"></lucide-icon>
                    </button>
                }
            </div>

            @if (!showHistory()) {
                <div class="px-3 py-2 border-b border-border/40 bg-black/10 shrink-0 space-y-2">
                    <div class="flex items-center gap-2">
                        <div class="flex-1 flex gap-1 p-1 rounded-xl bg-muted/40 border border-border/50">
                            <button
                                class="flex-1 px-3 py-1.5 text-[11px] font-semibold rounded-lg transition-colors"
                                [class.bg-teal-600]="aiMode() === 'chat'"
                                [class.text-white]="aiMode() === 'chat'"
                                [class.text-muted-foreground]="aiMode() !== 'chat'"
                                (click)="setAiMode('chat')">
                                Chat
                            </button>
                            <button
                                class="flex-1 px-3 py-1.5 text-[11px] font-semibold rounded-lg transition-colors"
                                [class.bg-teal-600]="aiMode() === 'canvas'"
                                [class.text-white]="aiMode() === 'canvas'"
                                [class.text-muted-foreground]="aiMode() !== 'canvas'"
                                (click)="setAiMode('canvas')">
                                Canvas
                            </button>
                        </div>
                        @if (aiMode() === 'canvas') {
                            <span class="text-[10px] uppercase tracking-[0.16em] text-teal-300/90">Note Editing</span>
                        }
                    </div>

                    @if (aiMode() === 'canvas') {
                        <div class="rounded-xl border border-teal-500/20 bg-teal-950/15 p-3 space-y-2">
                            <div class="grid grid-cols-2 gap-1 rounded-lg bg-black/20 p-1" data-testid="canvas-agent-mode">
                                <button class="rounded-md px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em]"
                                    [class.bg-teal-700]="canvasIntent() === 'agent'"
                                    [class.text-white]="canvasIntent() === 'agent'"
                                    [class.text-muted-foreground]="canvasIntent() !== 'agent'"
                                    (click)="canvasIntent.set('agent')">App agent</button>
                                <button class="rounded-md px-2 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em]"
                                    [class.bg-amber-500]="canvasIntent() === 'research'"
                                    [class.text-black]="canvasIntent() === 'research'"
                                    [class.text-muted-foreground]="canvasIntent() !== 'research'"
                                    (click)="canvasIntent.set('research')">Deep research</button>
                            </div>
                            <div class="flex items-center justify-between gap-2">
                                <div class="min-w-0">
                                    <div class="text-[10px] uppercase tracking-[0.14em] text-teal-300/80">Active Note</div>
                                    <div class="text-[13px] font-medium text-foreground truncate">
                                        {{ activeCanvasNote()?.title || activeCanvasNote()?.id || 'No open note' }}
                                    </div>
                                </div>
                                @if (pendingApprovals().length > 0) {
                                    <div class="text-[10px] font-medium text-amber-300">
                                        {{ pendingApprovals().length }} approval{{ pendingApprovals().length === 1 ? '' : 's' }}
                                    </div>
                                }
                            </div>
                            <div class="grid grid-cols-1 gap-2">
                                <div class="rounded-lg border border-white/5 bg-black/15 px-2.5 py-2">
                                    <div class="text-[10px] uppercase tracking-[0.14em] text-muted-foreground mb-1">Editor</div>
                                    <div class="text-[12px] text-foreground/90">{{ liveSelectionLabel() }}</div>
                                </div>
                                <div class="rounded-lg border border-white/5 bg-black/15 px-2.5 py-2">
                                    <div class="text-[10px] uppercase tracking-[0.14em] text-muted-foreground mb-1">Attached To Chat</div>
                                    <div class="text-[12px] text-foreground/90">{{ attachedSelectionLabel() }}</div>
                                    @if (canvasSelectionContext()?.text) {
                                        <div class="mt-2 text-[11px] leading-relaxed text-foreground/80 max-h-20 overflow-auto whitespace-pre-wrap">
                                            {{ canvasSelectionContext()?.text }}
                                        </div>
                                    }
                                </div>
                            </div>
                            @if (!hasCanvasDocument()) {
                                <div class="text-[11px] text-amber-300/90">
                                    Open a note to let Canvas inspect, highlight, and propose edits.
                                </div>
                            }
                        </div>
                        <app-canvas-run-inspector />
                    }
                </div>
            }

            <!-- Settings Panel -->
            @if (showSettings()) {
                <div class="settings-panel p-3 border-b border-border/50 bg-muted/30 space-y-3">
                    <!-- Provider Tabs -->
                    <div class="flex gap-1 p-1 bg-muted/50 rounded-lg">
                        <button 
                            class="flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                            [class.bg-teal-600]="activeProvider() === 'google'"
                            [class.text-white]="activeProvider() === 'google'"
                            [class.text-muted-foreground]="activeProvider() !== 'google'"
                            (click)="activeProvider.set('google')">
                            Google Gemini
                        </button>
                        <button 
                            class="flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                            [class.bg-teal-600]="activeProvider() === 'go-openrouter'"
                            [class.text-white]="activeProvider() === 'go-openrouter'"
                            [class.text-muted-foreground]="activeProvider() !== 'go-openrouter'"
                            (click)="activeProvider.set('go-openrouter')">
                            OpenRouter (Phoenix)
                        </button>
                        <button
                            class="flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                            [class.bg-teal-600]="activeProvider() === 'nvidia-nim'"
                            [class.text-white]="activeProvider() === 'nvidia-nim'"
                            [class.text-muted-foreground]="activeProvider() !== 'nvidia-nim'"
                            (click)="activeProvider.set('nvidia-nim')">
                            NVIDIA NIM
                        </button>
                    </div>

                    <!-- Google GenAI Settings -->
                    @if (activeProvider() === 'google') {
                        <div class="space-y-1">
                            <label class="text-xs font-medium text-muted-foreground">Google AI API Key</label>
                            <input 
                                type="password"
                                class="w-full px-3 py-2 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                                placeholder="AIza..."
                                [value]="googleApiKeyInput()"
                                (input)="googleApiKeyInput.set($any($event.target).value)"
                            />
                        </div>
                        <div class="space-y-1">
                            <label class="text-xs font-medium text-muted-foreground">Model</label>
                            <select 
                                class="w-full px-3 py-2 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                                [value]="googleModelInput()"
                                (change)="googleModelInput.set($any($event.target).value)"
                            >
                                @for (model of googleGenAI.availableModels; track model.id) {
                                    <option [value]="model.id">{{ model.name }} - {{ model.description }}</option>
                                }
                            </select>
                        </div>
                        @if (!googleGenAI.isConfigured()) {
                            <p class="text-xs text-amber-400">
                                ⚠️ Get your API key at <a href="https://aistudio.google.com/apikey" target="_blank" class="underline">aistudio.google.com</a>
                            </p>
                        }
                    }

                    <!-- Phoenix OpenRouter Settings -->
                    @if (activeProvider() === 'go-openrouter') {
                        <div class="space-y-1">
                            <label class="text-xs font-medium text-muted-foreground">OpenRouter API Key</label>
                            <input 
                                type="password"
                                class="w-full px-3 py-2 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                                placeholder="sk-or-..."
                                [value]="apiKeyInput()"
                                (input)="apiKeyInput.set($any($event.target).value)"
                            />
                        </div>
                        <!-- Model Picker -->
                        <div class="space-y-2">
                            <label class="text-xs font-medium text-muted-foreground">Model</label>

                            <!-- Current selection badge -->
                            <div class="px-2 py-1.5 bg-teal-900/30 border border-teal-500/30 rounded-md flex items-center justify-between">
                                <span class="text-xs text-teal-300 font-mono truncate">{{ selectedModel() || 'None selected' }}</span>
                            </div>

                            <!-- Add custom model input -->
                            <div class="flex gap-1">
                                <input
                                    type="text"
                                    class="flex-1 px-2 py-1.5 text-xs bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500 font-mono placeholder:text-muted-foreground/50"
                                    placeholder="provider/model-id:free"
                                    [value]="customModelInput()"
                                    (input)="customModelInput.set($any($event.target).value)"
                                    (keydown.enter)="addCustomModel()"
                                />
                                <button
                                    class="shrink-0 px-2 py-1.5 text-xs bg-teal-600 hover:bg-teal-500 text-white rounded-md transition-colors disabled:opacity-40"
                                    [disabled]="!customModelInput().trim()"
                                    (click)="addCustomModel()"
                                >Add</button>
                            </div>

                            <!-- Model pill list -->
                            <div class="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
                                @for (model of savedModels(); track model) {
                                    <div
                                        class="group flex items-center gap-0.5 pl-2 pr-1 py-0.5 rounded-full text-[10px] font-mono cursor-pointer border transition-colors"
                                        [class.bg-teal-600]="selectedModel() === model"
                                        [class.text-white]="selectedModel() === model"
                                        [class.border-teal-500]="selectedModel() === model"
                                        [class.bg-muted]="selectedModel() !== model"
                                        [class.text-muted-foreground]="selectedModel() !== model"
                                        [class.border-border]="selectedModel() !== model"
                                        [class.hover:bg-muted-foreground/10]="selectedModel() !== model"
                                        (click)="selectedModel.set(model)"
                                    >
                                        <span class="max-w-[140px] truncate">{{ model }}</span>
                                        <button
                                            class="ml-0.5 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity text-inherit leading-none"
                                            (click)="$event.stopPropagation(); removeModel(model)"
                                            title="Remove"
                                        >&times;</button>
                                    </div>
                                }
                            </div>
                        </div>
                        <div class="grid grid-cols-2 gap-2 mt-2">
                            <div class="space-y-1">
                                <label class="text-xs font-medium text-muted-foreground flex justify-between">
                                    <span>Temperature</span>
                                    <span>{{ temperatureInput() }}</span>
                                </label>
                                <input 
                                    type="range"
                                    min="0" max="2" step="0.1"
                                    class="w-full"
                                    [value]="temperatureInput()"
                                    (input)="temperatureInput.set(+$any($event.target).value)"
                                />
                            </div>
                            <div class="space-y-1">
                                <label class="text-xs font-medium text-muted-foreground flex justify-between">
                                    <span>Max Tokens</span>
                                    <span>{{ maxTokensInput() }}</span>
                                </label>
                                <input 
                                    type="range"
                                    min="256" max="131072" step="256"
                                    class="w-full"
                                    [value]="maxTokensInput()"
                                    (input)="maxTokensInput.set(+$any($event.target).value)"
                                />
                            </div>
                        </div>

                        <!-- OpenRouter Reasoning Controls -->
                        <div class="mt-2 p-2 rounded-md border border-teal-500/20 bg-teal-950/20 space-y-2">
                            <div class="flex items-center justify-between">
                                <div>
                                    <label class="text-xs font-medium">Reasoning</label>
                                    <p class="text-[10px] text-muted-foreground">Show model reasoning summaries and richer thought flow.</p>
                                </div>
                                <button
                                    class="relative w-11 h-6 rounded-full transition-colors"
                                    [class.bg-teal-600]="reasoningEnabledInput()"
                                    [class.bg-muted]="!reasoningEnabledInput()"
                                    (click)="reasoningEnabledInput.set(!reasoningEnabledInput())"
                                >
                                    <span
                                        class="absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"
                                        [class.translate-x-5]="reasoningEnabledInput()"
                                    ></span>
                                </button>
                            </div>

                            <div class="grid grid-cols-2 gap-2">
                                <div class="space-y-1">
                                    <label class="text-[10px] text-muted-foreground">Reasoning Effort</label>
                                    <select
                                        class="w-full px-2 py-1.5 text-xs bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                                        [value]="reasoningEffortInput()"
                                        (change)="reasoningEffortInput.set($any($event.target).value)"
                                    >
                                        <option value="low">Low</option>
                                        <option value="medium">Medium</option>
                                        <option value="high">High</option>
                                    </select>
                                </div>
                                <div class="space-y-1">
                                    <label class="text-[10px] text-muted-foreground flex justify-between">
                                        <span>Reasoning Tokens</span>
                                        <span>{{ reasoningMaxTokensInput() }}</span>
                                    </label>
                                    <input
                                        type="range"
                                        min="0" max="8192" step="128"
                                        class="w-full"
                                        [value]="reasoningMaxTokensInput()"
                                        (input)="reasoningMaxTokensInput.set(+$any($event.target).value)"
                                    />
                                </div>
                            </div>
                        </div>
                    }

                    <!-- NVIDIA NIM Settings -->
                    @if (activeProvider() === 'nvidia-nim') {
                        <div class="space-y-1">
                            <label class="text-xs font-medium text-muted-foreground">NVIDIA API Key</label>
                            <input
                                type="password"
                                class="w-full px-3 py-2 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                                placeholder="nvapi-..."
                                [value]="nvidiaApiKeyInput()"
                                (input)="nvidiaApiKeyInput.set($any($event.target).value)"
                            />
                        </div>
                        <div class="space-y-1">
                            <label class="text-xs font-medium text-muted-foreground">Model</label>
                            <select
                                class="w-full px-3 py-2 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500"
                                [value]="nvidiaModelInput()"
                                (change)="nvidiaModelInput.set($any($event.target).value)"
                            >
                                @for (model of nvidiaNim.availableModels; track model.id) {
                                    <option [value]="model.id">{{ model.name }} - {{ model.description }}</option>
                                }
                            </select>
                        </div>
                        <div class="grid grid-cols-2 gap-2 mt-2">
                            <div class="space-y-1">
                                <label class="text-xs font-medium text-muted-foreground flex justify-between">
                                    <span>Temperature</span>
                                    <span>{{ nvidiaTemperatureInput() }}</span>
                                </label>
                                <input
                                    type="range"
                                    min="0" max="2" step="0.1"
                                    class="w-full"
                                    [value]="nvidiaTemperatureInput()"
                                    (input)="nvidiaTemperatureInput.set(+$any($event.target).value)"
                                />
                            </div>
                            <div class="space-y-1">
                                <label class="text-xs font-medium text-muted-foreground flex justify-between">
                                    <span>Top P</span>
                                    <span>{{ nvidiaTopPInput() }}</span>
                                </label>
                                <input
                                    type="range"
                                    min="0.1" max="1" step="0.05"
                                    class="w-full"
                                    [value]="nvidiaTopPInput()"
                                    (input)="nvidiaTopPInput.set(+$any($event.target).value)"
                                />
                            </div>
                        </div>
                        <div class="space-y-1">
                            <label class="text-xs font-medium text-muted-foreground flex justify-between">
                                <span>Max Tokens</span>
                                <span>{{ nvidiaMaxTokensInput() }}</span>
                            </label>
                            <input
                                type="range"
                                min="512" max="32768" step="512"
                                class="w-full"
                                [value]="nvidiaMaxTokensInput()"
                                (input)="nvidiaMaxTokensInput.set(+$any($event.target).value)"
                            />
                        </div>
                    }

                    <!-- Observational Memory -->
                    <div class="mt-2 p-2 rounded-md border border-teal-500/20 bg-teal-950/10 space-y-2">
                        <div class="flex items-center justify-between">
                            <div>
                                <label class="text-xs font-medium">Observational Memory</label>
                                <p class="text-[10px] text-muted-foreground">Keep observer and reflector agents available for shared thread memory.</p>
                            </div>
                            <button
                                class="relative w-11 h-6 rounded-full transition-colors"
                                [class.bg-teal-600]="omEnabledInput()"
                                [class.bg-muted]="!omEnabledInput()"
                                (click)="omEnabledInput.set(!omEnabledInput())"
                            >
                                <span
                                    class="absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"
                                    [class.translate-x-5]="omEnabledInput()"
                                ></span>
                            </button>
                        </div>

                        @if (omEnabledInput()) {
                            <div class="space-y-2">
                                <div class="space-y-1">
                                    <label class="text-[10px] text-muted-foreground">OM Model</label>
                                    <input
                                        type="text"
                                        class="w-full px-3 py-2 text-sm bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500 font-mono placeholder:text-muted-foreground/60"
                                        placeholder="provider/model-id"
                                        [value]="omModelInput()"
                                        (input)="omModelInput.set($any($event.target).value)"
                                    />
                                </div>
                                <div class="grid grid-cols-2 gap-2">
                                    <div class="space-y-1">
                                        <label class="text-[10px] text-muted-foreground flex justify-between">
                                            <span>Observe Threshold</span>
                                            <span>{{ observeThresholdInput() }}</span>
                                        </label>
                                        <input
                                            type="range"
                                            min="100" max="10000" step="100"
                                            class="w-full"
                                            [value]="observeThresholdInput()"
                                            (input)="observeThresholdInput.set(+$any($event.target).value)"
                                        />
                                    </div>
                                    <div class="space-y-1">
                                        <label class="text-[10px] text-muted-foreground flex justify-between">
                                            <span>Reflect Threshold</span>
                                            <span>{{ reflectThresholdInput() }}</span>
                                        </label>
                                        <input
                                            type="range"
                                            min="500" max="20000" step="100"
                                            class="w-full"
                                            [value]="reflectThresholdInput()"
                                            (input)="reflectThresholdInput.set(+$any($event.target).value)"
                                        />
                                    </div>
                                </div>
                            </div>
                        }
                    </div>

                    <!-- Index Mode Toggle -->
                    <div class="flex items-center justify-between py-1">
                        <div class="flex items-center gap-2">
                            <lucide-icon [img]="DatabaseIcon" class="h-4 w-4 text-muted-foreground"></lucide-icon>
                            <div>
                                <label class="text-xs font-medium">Index Mode</label>
                                <p class="text-[10px] text-muted-foreground">Enable note & entity search</p>
                            </div>
                        </div>
                        <button
                            class="relative w-11 h-6 rounded-full transition-colors"
                            [class.bg-teal-600]="indexEnabled()"
                            [class.bg-muted]="!indexEnabled()"
                            (click)="toggleIndexMode()"
                        >
                            <span
                                class="absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"
                                [class.translate-x-5]="indexEnabled()"
                            ></span>
                        </button>
                    </div>

                    <!-- Custom Instructions (Collapsible) -->
                    <div class="border-t border-border/30 pt-2 mt-2">
                        <button 
                            class="flex items-center justify-between w-full py-1 group"
                            (click)="toggleSystemPrompt()">
                            <div class="flex items-center gap-2">
                                <lucide-icon [img]="SettingsIcon" class="h-4 w-4 text-muted-foreground group-hover:text-teal-400 transition-colors"></lucide-icon>
                                <div class="text-left">
                                    <label class="text-xs font-medium cursor-pointer group-hover:text-teal-400 transition-colors">Custom Instructions</label>
                                    <p class="text-[10px] text-muted-foreground">Customize Kammi's persona & behavior</p>
                                </div>
                            </div>
                            <div class="text-[10px] text-muted-foreground group-hover:text-teal-400 transition-colors">
                                {{ showSystemPrompt() ? 'Hide' : 'Edit' }}
                            </div>
                        </button>
                        
                        @if (showSystemPrompt()) {
                            <div class="mt-2 space-y-2 pl-1 animation-slide-down">
                                <textarea
                                    class="w-full h-32 px-3 py-2 text-xs bg-background border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-teal-500 resize-none leading-relaxed"
                                    [value]="systemPromptInput()"
                                    (input)="systemPromptInput.set($any($event.target).value)"
                                    placeholder="Enter system instructions..."
                                ></textarea>
                                <div class="flex justify-end">
                                    <button 
                                        class="flex items-center gap-1.5 px-2 py-1 text-[10px] text-muted-foreground hover:text-teal-400 hover:bg-teal-500/10 rounded transition-colors"
                                        (click)="resetSystemPrompt()"
                                        title="Reset to default Kammi persona">
                                        <lucide-icon [img]="RotateCcwIcon" class="h-3 w-3"></lucide-icon>
                                        Reset to Default
                                    </button>
                                </div>
                            </div>
                        }
                    </div>

                    <!-- Save/Cancel Buttons -->
                    <div class="flex gap-2">
                        <button 
                            class="flex-1 px-3 py-1.5 text-xs font-medium bg-teal-600 hover:bg-teal-700 text-white rounded-md transition-colors"
                            (click)="saveSettings()">
                            Save
                        </button>
                        <button 
                            class="px-3 py-1.5 text-xs font-medium bg-muted hover:bg-muted/80 rounded-md transition-colors"
                            (click)="showSettings.set(false)">
                            Cancel
                        </button>
                    </div>

                    <!-- Active Provider Indicator -->
                    @if (googleGenAI.isConfigured() || isGoConfigured() || isNvidiaConfigured()) {
                        <div class="text-[10px] text-center text-muted-foreground">
                            Using: <span class="text-teal-400 font-medium">{{ getActiveProviderName() }}</span>
                        </div>
                    }
                </div>
            }

            <!-- History Panel -->
            @if (showHistory()) {
                <div class="flex-1 overflow-y-auto p-3 space-y-2">
                    @for (session of sessions(); track session.id) {
                        <button 
                            class="w-full p-3 text-left rounded-lg border transition-all"
                            [class.border-teal-500]="session.id === goChatService.currentThread()?.id"
                            [class.bg-teal-500/10]="session.id === goChatService.currentThread()?.id"
                            [class.border-border/50]="session.id !== goChatService.currentThread()?.id"
                            [class.hover:bg-muted/50]="session.id !== goChatService.currentThread()?.id"
                            (click)="selectSession(session.id)"
                        >
                            <div class="flex items-center justify-between">
                                <span class="text-xs font-medium truncate">{{ session.id }}</span>
                                <span class="text-[10px] text-muted-foreground">{{ session.messageCount }} msgs</span>
                            </div>
                            <div class="text-[10px] text-muted-foreground mt-1">
                                {{ formatSessionDate(session.createdAt) }}
                            </div>
                            @if (session.preview) {
                                <div class="text-xs text-muted-foreground mt-1 truncate italic">
                                    "{{ session.preview }}"
                                </div>
                            }
                        </button>
                    } @empty {
                        <div class="text-center py-8 text-muted-foreground">
                            <lucide-icon [img]="HistoryIcon" class="h-8 w-8 mx-auto opacity-30 mb-2"></lucide-icon>
                            <p class="text-xs">No chat history yet</p>
                        </div>
                    }
                </div>
            }

            <!-- Chat Area -->
            <div class="flex-1 flex flex-col min-w-0" [class.hidden]="showHistory()">
                <div #messagesContainer class="flex-1 overflow-y-auto px-3 py-4 space-y-4 custom-scrollbar">
                    @if (displayMessages().length === 0) {
                        <div class="flex flex-col items-center justify-center h-full text-center mt-6">
                            <div class="w-16 h-16 rounded-2xl bg-teal-500/10 flex items-center justify-center mb-4 border border-teal-500/20">
                                <lucide-icon [img]="SparklesIcon" class="h-8 w-8 text-teal-400"></lucide-icon>
                            </div>
                            <h2 class="text-xl font-semibold text-foreground mb-2">Kammi AI</h2>
                        </div>
                    }

                    @for (msg of displayMessages(); track msg.id) {
                        @if (msg.role === 'system' && msg.activitySteps) {
                            <div class="inline-trace my-2 max-w-[95%] mx-auto">
                                <div class="inline-trace-header">
                                    <div class="inline-trace-title"><span class="brain-mark">*</span><span>Thinking</span></div>
                                    <div class="inline-trace-status">{{ msg.statusText }}</div>
                                </div>
                                <div class="inline-trace-steps">
                                    @for (step of msg.activitySteps; track step.id) {
                                        <div class="inline-trace-step" [class]="step.status">
                                            <div class="inline-trace-dot"></div>
                                            <div>
                                                <div class="inline-trace-step-title">{{ step.label }}</div>
                                                @if (step.detail) { <div class="inline-trace-step-detail">{{ step.detail }}</div> }
                                            </div>
                                            @if (step.latencyMs !== undefined) { <span class="inline-trace-step-latency">{{ step.latencyMs }}ms</span> }
                                        </div>
                                    }
                                </div>
                            </div>
                        } @else if (msg.role !== 'system') {
                            <div class="flex gap-2 w-full max-w-[95%] mx-auto" [class.flex-row-reverse]="msg.role === 'user'">
                                <div class="w-6 h-6 rounded-md shrink-0 flex items-center justify-center border"
                                    [class.bg-teal-500/20]="msg.role === 'assistant'" [class.border-teal-500/30]="msg.role === 'assistant'"
                                    [class.bg-muted]="msg.role === 'user'" [class.border-border]="msg.role === 'user'">
                                    <lucide-icon [img]="msg.role === 'user' ? UserIcon : BotIcon" class="h-3.5 w-3.5"
                                        [class.text-teal-400]="msg.role === 'assistant'" [class.text-muted-foreground]="msg.role === 'user'">
                                    </lucide-icon>
                                </div>
                                <div class="flex-1 min-w-0">
                                    <div class="flex items-center gap-1 mb-1" [class.justify-end]="msg.role === 'user'">
                                        <span class="text-[9px] font-medium" [class.text-teal-400]="msg.role === 'assistant'" [class.text-muted-foreground]="msg.role === 'user'">
                                            {{ msg.role === 'user' ? 'You' : 'Kammi' }}
                                        </span>
                                        <span class="text-[9px] text-muted-foreground/70">{{ formatTime(msg.timestamp) }}</span>
                                    </div>
                                    <div class="message-bubble px-3 py-2 rounded-xl text-[13px] leading-relaxed whitespace-pre-wrap"
                                        [class.user-bubble]="msg.role === 'user'" [class.assistant-bubble]="msg.role === 'assistant'">
                                        {{ msg.content }}
                                        @if (msg.isStreaming) {
                                            <span class="inline-flex gap-0.5 ml-1 align-middle">
                                                <span class="w-1 h-1 rounded-full bg-teal-400 animate-bounce" style="animation-delay: 0ms"></span>
                                                <span class="w-1 h-1 rounded-full bg-teal-400 animate-bounce" style="animation-delay: 150ms"></span>
                                                <span class="w-1 h-1 rounded-full bg-teal-400 animate-bounce" style="animation-delay: 300ms"></span>
                                            </span>
                                        }
                                    </div>
                                </div>
                            </div>
                        }
                    }

                    @if (pendingApprovals().length > 0) {
                        <div class="max-w-[95%] mx-auto space-y-3">
                            @for (approval of pendingApprovals(); track approval.id) {
                                <div class="rounded-xl border border-amber-500/30 bg-amber-950/20 p-3">
                                    <div class="text-[11px] font-semibold text-amber-300 mb-1">Approval Required</div>
                                    <div class="text-[13px] text-foreground mb-2">{{ approval.summary }}</div>
                                    @if (approval.diffPreview) {
                                        <pre class="text-[11px] whitespace-pre-wrap rounded-lg bg-black/20 border border-white/5 p-2 text-amber-100/90 max-h-48 overflow-auto">{{ approval.diffPreview }}</pre>
                                    }
                                    <div class="flex gap-2 mt-3">
                                        <button
                                            class="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-teal-600 hover:bg-teal-500 text-white disabled:opacity-50"
                                            [disabled]="approvalBusy() === approval.id"
                                            (click)="handleApprovalDecision(approval, true)">
                                            Approve
                                        </button>
                                        <button
                                            class="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-rose-600/80 hover:bg-rose-500 text-white disabled:opacity-50"
                                            [disabled]="approvalBusy() === approval.id"
                                            (click)="handleApprovalDecision(approval, false)">
                                            Reject
                                        </button>
                                    </div>
                                </div>
                            }
                        </div>
                    }
                </div>
                <div class="shrink-0 border-t border-border/50 p-3 chat-input-area bg-gradient-to-t from-teal-900/10 to-transparent">
                    <div class="flex items-end gap-2 relative">
                        <textarea #messageInput class="w-full pl-3 pr-10 py-2.5 text-[13px] rounded-xl border border-border bg-background focus:outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500/30 resize-none transition-all placeholder:text-muted-foreground/60 shadow-sm"
                            [placeholder]="aiMode() === 'canvas' ? (canvasIntent() === 'research' ? 'Research a question and write the verified result to this note...' : 'Ask Kammi to inspect or edit the open note...') : 'Ask Kammi anything...'" [(ngModel)]="currentMessage" (keydown.enter)="onEnterKey($event)" [disabled]="isStreaming()" rows="1" style="max-height: 120px"></textarea>
                        <button class="absolute right-1.5 bottom-1.5 w-7 h-7 rounded-lg flex items-center justify-center transition-all send-btn"
                            [class.active]="currentMessage.trim() && !isStreaming() && !canvasRuns.busy()" [disabled]="!currentMessage.trim() || isStreaming() || canvasRuns.busy()" (click)="sendMessage()">
                            <lucide-icon [img]="SendIcon" class="h-3.5 w-3.5"></lucide-icon>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `,
    styles: [`
        /* ============================================
           AI CHAT PANEL - Premium Teal Umbra Theme
           Matches app header/footer gradient aesthetic
           ============================================ */

        /* CRITICAL: Host must fill parent completely */
        :host {
            display: flex;
            flex-direction: column;
            height: 100%;
            min-height: 0;
            overflow: hidden;
        }

        .ai-chat-wrapper {
            display: flex;
            flex-direction: column;
            flex: 1 1 0;
            min-height: 0;
            overflow: hidden;
            background: linear-gradient(180deg, 
                hsl(var(--background)) 0%, 
                hsl(var(--background)) 85%,
                rgba(17, 94, 89, 0.05) 100%
            );
        }

        /* Header - subtle teal gradient like app header */
        .chat-header {
            flex-shrink: 0;
            background: linear-gradient(to right, 
                rgba(17, 94, 89, 0.15) 0%, 
                rgba(19, 78, 74, 0.1) 50%, 
                rgba(15, 42, 46, 0.08) 100%
            );
            border-bottom: 1px solid rgba(20, 184, 166, 0.15);
        }

        .chat-action-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border-radius: 6px;
            background: transparent;
            border: none;
            color: hsl(var(--muted-foreground));
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .chat-action-btn:hover {
            background: rgba(20, 184, 166, 0.2);
            color: #14b8a6;
            transform: scale(1.05);
        }

        .settings-panel {
            animation: slideDown 0.2s ease-out;
            background: linear-gradient(180deg,
                rgba(17, 94, 89, 0.08) 0%,
                transparent 100%
            );
            border-bottom: 1px solid rgba(20, 184, 166, 0.1) !important;
        }

        @keyframes slideDown {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Chat container - must constrain quikchat to available space */
        .chat-container {
            flex: 1 1 0 !important;
            min-height: 0 !important;
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
        }

        :host ::ng-deep .inline-trace {
            display: grid;
            gap: 10px;
        }

        :host ::ng-deep .inline-trace-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        :host ::ng-deep .inline-trace-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #67e8f9;
        }

        :host ::ng-deep .inline-trace-title .brain-mark {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 20px;
            height: 20px;
            border-radius: 9999px;
            background: rgba(20, 184, 166, 0.14);
            border: 1px solid rgba(45, 212, 191, 0.2);
            color: #5eead4;
            font-size: 12px;
        }

        :host ::ng-deep .inline-trace-status {
            font-size: 11px;
            color: hsl(var(--muted-foreground));
        }

        :host ::ng-deep .inline-trace-steps {
            display: grid;
            gap: 8px;
        }

        :host ::ng-deep .inline-trace-step {
            display: grid;
            grid-template-columns: 10px 1fr auto;
            gap: 8px;
            align-items: start;
            padding: 8px 10px;
            border: 1px solid rgba(39, 39, 42, 0.9);
            border-radius: 12px;
            background: rgba(9, 9, 11, 0.52);
        }

        :host ::ng-deep .inline-trace-dot {
            width: 8px;
            height: 8px;
            margin-top: 4px;
            border-radius: 9999px;
            background: rgba(20, 184, 166, 0.55);
            box-shadow: 0 0 0 3px rgba(20, 184, 166, 0.12);
        }

        :host ::ng-deep .inline-trace-step.running .inline-trace-dot {
            background: rgb(45, 212, 191);
            box-shadow: 0 0 0 3px rgba(45, 212, 191, 0.15), 0 0 12px rgba(45, 212, 191, 0.35);
        }

        :host ::ng-deep .inline-trace-step.error .inline-trace-dot {
            background: rgb(248, 113, 113);
            box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.15);
        }

        :host ::ng-deep .inline-trace-step-title {
            font-size: 15px;
            line-height: 1.25;
            color: hsl(var(--foreground));
        }

        :host ::ng-deep .inline-trace-step-detail {
            margin-top: 2px;
            font-size: 12px;
            line-height: 1.4;
            color: hsl(var(--muted-foreground));
            word-break: break-word;
        }

        :host ::ng-deep .inline-trace-step-latency {
            font-size: 11px;
            color: hsl(var(--muted-foreground));
            white-space: nowrap;
        }



        /* ============================================
           QUIKCHAT OVERRIDES - Premium Teal Theme
           Using actual quikchat class names!
           ============================================ */

        /* Main container - flex column with input at bottom */
        :host ::ng-deep .quikchat-base {
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            font-family: inherit !important;
            box-shadow: none !important;
        }

        /* Hide title area - we have our own header */
        :host ::ng-deep .quikchat-title-area {
            display: none !important;
        }

        /* Messages area - flex grow to push input down */
        :host ::ng-deep .quikchat-messages-area {
            flex: 1 1 auto !important;
            min-height: 0 !important;
            overflow-y: auto !important;
            padding: 20px 16px !important;
            background: transparent !important;
            scrollbar-width: thin;
            scrollbar-color: rgba(20, 184, 166, 0.3) transparent;
        }

        /* Message wrapper */
        :host ::ng-deep .quikchat-message {
            margin-bottom: 18px;
            max-width: 92%;
            animation: fadeInUp 0.3s ease-out;
        }

        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        :host ::ng-deep .quikchat-message.left,
        :host ::ng-deep .quikchat-message.left-singleline,
        :host ::ng-deep .quikchat-message.left-multiline {
            margin-right: auto !important;
            padding: 12px 16px !important;
            background: linear-gradient(135deg,
                rgba(20, 184, 166, 0.06) 0%,
                transparent 100%
            ) !important;
            border-left: 2px solid rgba(20, 184, 166, 0.4) !important;
            border-radius: 0 12px 12px 0 !important;
            color: hsl(var(--foreground)) !important;
        }

        :host ::ng-deep .quikchat-message.right,
        :host ::ng-deep .quikchat-message.right-singleline,
        :host ::ng-deep .quikchat-message.right-multiline {
            margin-left: auto !important;
            padding: 12px 16px !important;
            background: linear-gradient(135deg, 
                rgba(17, 94, 89, 0.25) 0%, 
                rgba(20, 184, 166, 0.15) 100%
            ) !important;
            border: 1px solid rgba(20, 184, 166, 0.3) !important;
            border-radius: 18px 18px 4px 18px !important;
            color: hsl(var(--foreground)) !important;
            backdrop-filter: blur(12px);
            box-shadow: 
                0 2px 8px rgba(0, 0, 0, 0.1),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
        }

        /* ============================================
           INPUT AREA - Fixed at Bottom, Umbra Themed
           ============================================ */
        :host ::ng-deep .quikchat-input-area {
            flex: 0 0 auto !important;
            display: flex !important;
            align-items: center !important;
            gap: 12px !important;
            padding: 16px !important;
            margin: 0 !important;
            height: auto !important;
            min-height: 72px !important;
            background: linear-gradient(to right, 
                rgba(17, 94, 89, 0.12) 0%, 
                rgba(19, 78, 74, 0.08) 50%, 
                rgba(15, 42, 46, 0.1) 100%
            ) !important;
            border-top: 1px solid rgba(20, 184, 166, 0.2) !important;
            border-radius: 0 !important;
        }

        /* Text Input - Dark themed with teal focus */
        :host ::ng-deep .quikchat-input-textbox {
            flex: 1 !important;
            padding: 12px 16px !important;
            border: 1px solid rgba(20, 184, 166, 0.2) !important;
            border-radius: 12px !important;
            background: rgba(0, 0, 0, 0.3) !important;
            color: hsl(var(--foreground)) !important;
            font-size: 14px !important;
            font-family: inherit !important;
            outline: none !important;
            transition: all 0.2s ease !important;
            margin: 0 !important;
            box-sizing: border-box !important;
            height: auto !important;
            min-height: 44px !important;
        }

        :host ::ng-deep .quikchat-input-textbox:focus {
            border-color: #14b8a6 !important;
            background: rgba(0, 0, 0, 0.4) !important;
            box-shadow: 
                0 0 0 3px rgba(20, 184, 166, 0.15),
                0 0 20px rgba(20, 184, 166, 0.1) !important;
        }

        :host ::ng-deep .quikchat-input-textbox::placeholder {
            color: hsl(var(--muted-foreground)) !important;
        }

        /* SEND BUTTON - Teal Umbra Gradient (matches header/footer) */
        :host ::ng-deep .quikchat-input-send-btn {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            height: 44px !important;
            padding: 0 20px !important;
            border-radius: 10px !important;
            background: linear-gradient(135deg, 
                #115e59 0%, 
                #134e4a 50%, 
                #0f2a2e 100%
            ) !important;
            border: 1px solid rgba(20, 184, 166, 0.3) !important;
            color: #e2e8f0 !important;
            font-size: 14px !important;
            font-weight: 600 !important;
            font-family: inherit !important;
            cursor: pointer !important;
            transition: all 0.2s ease !important;
            box-shadow: 
                0 4px 12px rgba(17, 94, 89, 0.4),
                inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
            white-space: nowrap !important;
        }

        :host ::ng-deep .quikchat-input-send-btn:hover {
            transform: translateY(-1px) !important;
            box-shadow: 
                0 6px 16px rgba(17, 94, 89, 0.5),
                inset 0 1px 0 rgba(255, 255, 255, 0.15) !important;
        }

        :host ::ng-deep .quikchat-input-send-btn:active {
            transform: translateY(0) !important;
            box-shadow: 
                0 2px 8px rgba(17, 94, 89, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        }

        /* ============================================
           LIGHT MODE - Adjusted for light sidebar
           ============================================ */
        :host-context(.light) .ai-chat-wrapper {
            background: linear-gradient(180deg, 
                hsl(var(--background)) 0%, 
                hsl(var(--background)) 85%,
                rgba(17, 94, 89, 0.03) 100%
            );
        }

        :host-context(.light) .chat-header {
            background: linear-gradient(to right, 
                rgba(17, 94, 89, 0.08) 0%, 
                rgba(19, 78, 74, 0.05) 50%, 
                rgba(15, 42, 46, 0.03) 100%
            );
        }

        :host-context(.light) ::ng-deep .quikchat-message.left,
        :host-context(.light) ::ng-deep .quikchat-message.left-singleline,
        :host-context(.light) ::ng-deep .quikchat-message.left-multiline {
            color: #18181b !important;
            background: linear-gradient(135deg,
                rgba(20, 184, 166, 0.08) 0%,
                rgba(20, 184, 166, 0.02) 100%
            ) !important;
        }

        :host-context(.light) ::ng-deep .quikchat-message.right,
        :host-context(.light) ::ng-deep .quikchat-message.right-singleline,
        :host-context(.light) ::ng-deep .quikchat-message.right-multiline {
            background: linear-gradient(135deg, 
                rgba(17, 94, 89, 0.15) 0%, 
                rgba(20, 184, 166, 0.1) 100%
            ) !important;
            border-color: rgba(20, 184, 166, 0.25) !important;
            color: #18181b !important;
        }

        :host-context(.light) ::ng-deep .quikchat-input-area {
            background: linear-gradient(to right, 
                rgba(17, 94, 89, 0.06) 0%, 
                rgba(19, 78, 74, 0.04) 50%, 
                rgba(15, 42, 46, 0.05) 100%
            ) !important;
            border-top-color: rgba(20, 184, 166, 0.15) !important;
        }

        :host-context(.light) ::ng-deep .quikchat-input-textbox {
            background: white !important;
            border-color: rgba(20, 184, 166, 0.2) !important;
            color: #18181b !important;
        }

        :host-context(.light) ::ng-deep .quikchat-input-textbox:focus {
            background: white !important;
            box-shadow: 
                0 0 0 3px rgba(20, 184, 166, 0.1),
                0 0 20px rgba(20, 184, 166, 0.05) !important;
        }

        :host-context(.light) ::ng-deep .quikchat-input-textbox::placeholder {
            color: #9ca3af !important;
        }
    `]
})
export class AiChatPanelComponent implements AfterViewInit, OnDestroy {
    @ViewChild('messagesContainer') messagesContainer!: ElementRef<HTMLDivElement>;
    @ViewChild('messageInput') messageInput!: ElementRef<HTMLTextAreaElement>;

    displayMessages = signal<DisplayMessage[]>([]);
    isStreaming = signal(false);
    currentMessage = '';

    // PhoenixChatService for persistence, run state, and OpenRouter streaming
    goChatService = inject(PhoenixChatService);
    // Google GenAI fallback (TypeScript)
    googleGenAI = inject(GoogleGenAIService);
    nvidiaNim = inject(NvidiaNimService);
    private orchestrator = inject(OrchestratorService);
    private readonly chatContextClipStore = inject(ChatContextClipStore);
    private readonly toolHost = inject(ChatToolHostService);
    private readonly aiSidebarMode = inject(AiSidebarModeService);
    private readonly workspace = inject(EditorAgentWorkspaceService);
    private readonly noteEditorStore = inject(NoteEditorStore);
    readonly canvasRuns = inject(CanvasAgentRunService);
    readonly canvasIntent = signal<'agent' | 'research'>('agent');
    private goChatInitialized = false;
    readonly aiMode = this.aiSidebarMode.mode;
    readonly canvasSelectionContext = this.aiSidebarMode.selectionContext;
    readonly liveEditorSelection = this.workspace.liveSelection;
    readonly activeCanvasNote = computed(() => this.noteEditorStore.currentNote());
    readonly hasCanvasDocument = computed(() => !!this.activeCanvasNote());
    readonly liveSelectionLabel = computed(() => {
        const selection = this.liveEditorSelection();
        if (!selection || selection.empty) {
            return 'No live editor selection';
        }
        return `Live selection ${selection.from}-${selection.to} (${selection.text.length} chars)`;
    });
    readonly attachedSelectionLabel = computed(() => {
        const selection = this.canvasSelectionContext();
        if (!selection) {
            return 'No attached note range';
        }
        return `Attached range ${selection.from}-${selection.to} • approval required`;
    });

    // Icon references for template
    readonly PlusIcon = Plus;
    readonly Trash2Icon = Trash2;
    readonly DownloadIcon = Download;
    readonly SettingsIcon = Settings;
    readonly HistoryIcon = History;
    readonly ArrowLeftIcon = ArrowLeft;
    readonly DatabaseIcon = Database;
    readonly BrainIcon = Brain;
    readonly RotateCcwIcon = RotateCcw;
    readonly BotIcon = Bot;
    readonly UserIcon = User;
    readonly SparklesIcon = Sparkles;
    readonly SendIcon = Send;

    // Settings panel state
    showSettings = signal(false);
    activeProvider = signal<'google' | 'go-openrouter' | 'nvidia-nim'>('go-openrouter'); // Go-first
    constructor() {
        effect(() => {
            this.goChatService.currentThread();
            this.goChatService.messages();
            this.goChatService.threads();
            untracked(() => {
                this.restoreHistory();
            });
        });
        effect(() => {
            const ticket = this.aiSidebarMode.composerFocusTicket();
            if (ticket === 0) return;
            this.showHistory.set(false);
            this.showSettings.set(false);
            setTimeout(() => this.focusComposer(), 0);
        });
    }

    onEnterKey(event: Event): void {
        const kbEvent = event as KeyboardEvent;
        if (kbEvent.shiftKey) return;
        kbEvent.preventDefault();
        this.sendMessage();
    }

    setAiMode(mode: AiSidebarMode): void {
        if (mode === 'canvas') {
            this.aiSidebarMode.switchToCanvas();
            return;
        }
        this.aiSidebarMode.switchToChat();
    }

    private focusComposer(): void {
        this.messageInput?.nativeElement?.focus();
    }


    // Custom Instructions
    showSystemPrompt = signal(false);
    systemPromptInput = signal(KAMMI_SYSTEM_PROMPT);

    // OpenRouter settings
    apiKeyInput = signal('');
    selectedModel = signal('nvidia/nemotron-3-nano-30b-a3b:free');
    temperatureInput = signal(0.7);
    maxTokensInput = signal(2048);
    reasoningEnabledInput = signal(true);
    reasoningEffortInput = signal<'low' | 'medium' | 'high'>('medium');
    reasoningMaxTokensInput = signal(1024);
    omEnabledInput = signal(true);
    omModelInput = signal('nvidia/nemotron-3-super-120b-a12b:free');
    observeThresholdInput = signal(1000);
    reflectThresholdInput = signal(4000);

    // Per-message activity/timeline state (inline chat trace)
    activitySteps = signal<ActivityTraceStep[]>([]);
    pendingApprovals = signal<ChatApprovalRequest[]>([]);
    currentRunId = signal<string | null>(null);
    approvalBusy = signal<string | null>(null);
    private traceCounter = 0;
    private readonly traceStartedAt = new Map<string, number>();
    private currentTraceMsgId: string | null = null;


    // Persisted model list — seed + user-added models
    private readonly MODELS_KEY = 'openrouter:models';
    private readonly MODEL_SEEDS = [
        'nvidia/nemotron-3-nano-30b-a3b:free',
        'meta-llama/llama-3.3-70b-instruct:free',
        'google/gemini-3-flash-preview',
        'deepseek/deepseek-r1:free',
        'mistralai/mistral-nemo:free',
        'z-ai/glm-4.5-air:free',
        'stepfun/step-3.5-flash:free',
        'arcee-ai/trinity-large-preview:free',
    ];
    savedModels = signal<string[]>(this.loadSavedModels());
    customModelInput = signal('');

    // Google GenAI settings
    googleApiKeyInput = signal('');
    googleModelInput = signal('gemini-3-flash-preview');

    // NVIDIA NIM settings
    nvidiaApiKeyInput = signal('');
    nvidiaModelInput = signal('moonshotai/kimi-k2-thinking');
    nvidiaTemperatureInput = signal(1);
    nvidiaTopPInput = signal(0.9);
    nvidiaMaxTokensInput = signal(16384);

    // Index toggle - enables tool calling
    indexEnabled = signal(false);

    /** True when a Phoenix OpenRouter API key has been entered/saved. */
    readonly isGoConfigured = computed(() => !!this.apiKeyInput());
    readonly isNvidiaConfigured = computed(() => !!this.nvidiaApiKeyInput());

    // History panel state
    showHistory = signal(false);
    sessions = signal<SessionInfo[]>([]);

    // Current streaming message ID
    private currentBotMsgId: string | null = null;
    private chat: any = null;
    private scriptLoaded = false;

    ngAfterViewInit(): void {

        // Pre-fill Phoenix OpenRouter config from saved openrouter:config (shared key store)
        const savedOrConfig = getSetting<ChatConfig | null>('openrouter:config', null);
        if (savedOrConfig) {
            this.apiKeyInput.set(savedOrConfig.apiKey || '');
            const restoredModel = savedOrConfig.model || 'nvidia/nemotron-3-nano-30b-a3b:free';
            this.selectedModel.set(restoredModel);
            // If the saved model isn't in the list yet, add it
            if (!this.savedModels().includes(restoredModel)) {
                this.savedModels.update(list => [restoredModel, ...list]);
                setSetting(this.MODELS_KEY, this.savedModels());
            }
            this.temperatureInput.set(savedOrConfig.temperature ?? 0.7);
            this.maxTokensInput.set(savedOrConfig.maxTokens ?? 2048);
            this.reasoningEnabledInput.set(savedOrConfig.reasoningEnabled ?? true);
            this.reasoningEffortInput.set(savedOrConfig.reasoningEffort ?? 'medium');
            this.reasoningMaxTokensInput.set(savedOrConfig.reasoningMaxTokens ?? 1024);
            this.omEnabledInput.set(savedOrConfig.omEnabled ?? true);
            this.omModelInput.set(savedOrConfig.omModel || 'nvidia/nemotron-3-super-120b-a12b:free');
            this.observeThresholdInput.set(savedOrConfig.observeThreshold ?? 1000);
            this.reflectThresholdInput.set(savedOrConfig.reflectThreshold ?? 4000);
        }

        const googleConfig = this.googleGenAI.config();
        if (googleConfig) {
            this.googleApiKeyInput.set(googleConfig.apiKey || '');
            this.googleModelInput.set(googleConfig.model || 'gemini-2.0-flash');
        }

        const nvidiaConfig = this.nvidiaNim.config();
        if (nvidiaConfig) {
            this.nvidiaApiKeyInput.set(nvidiaConfig.apiKey || '');
            this.nvidiaModelInput.set(nvidiaConfig.model || 'moonshotai/kimi-k2-thinking');
            this.nvidiaTemperatureInput.set(nvidiaConfig.temperature ?? 1);
            this.nvidiaTopPInput.set(nvidiaConfig.topP ?? 0.9);
            this.nvidiaMaxTokensInput.set(nvidiaConfig.maxTokens ?? 16384);
        }

        // Default to Phoenix OpenRouter; fallback to Google if configured
        if (this.googleGenAI.isConfigured() && !savedOrConfig?.apiKey) {
            this.activeProvider.set('google');
        } else if (this.nvidiaNim.isConfigured() && !savedOrConfig?.apiKey) {
            this.activeProvider.set('nvidia-nim');
        }

        // Initialize Phoenix chat service
        this.initPhoenixChatService();

        // Load saved system prompt
        const savedPrompt = getSetting<string | null>('chat:systemPrompt', null);
        if (savedPrompt) {
            this.systemPromptInput.set(savedPrompt);
        }

        const savedIndexMode = getSetting<boolean>('chat:indexMode', false);
        this.indexEnabled.set(savedIndexMode);
    }

    /**
     * Initialize Phoenix chat service with OpenRouter config.
     * This enables persistence + memory extraction.
     */
    private async initPhoenixChatService(): Promise<void> {
        if (this.goChatInitialized) return;
        // init() reads openrouter:config from Dexie internally when no arg provided

        await this.goChatService.init();
        this.goChatInitialized = true;
        console.log('[AiChatPanel] Phoenix chat service initialized');
    }

    ngOnDestroy(): void {
        this.displayMessages.set([]);
    }

    // -------------------------------------------------------------------------
    // Settings
    // -------------------------------------------------------------------------

    toggleSettings(): void {
        this.showSettings.update(v => !v);
    }

    saveSettings(): void {
        // Persist Phoenix OpenRouter config to the shared openrouter:config key
        if (this.apiKeyInput()) {
            const existingOrConfig = getSetting<ChatConfig | null>('openrouter:config', null);
            const orConfig: ChatConfig = {
                apiKey: this.apiKeyInput(),
                model: this.selectedModel(),
                temperature: this.temperatureInput(),
                maxTokens: this.maxTokensInput(),
                reasoningEnabled: this.reasoningEnabledInput(),
                reasoningEffort: this.reasoningEffortInput(),
                reasoningMaxTokens: this.reasoningMaxTokensInput(),
                includeReasoning: this.reasoningEnabledInput(),
                structuredOutput: existingOrConfig?.structuredOutput,
                plugins: existingOrConfig?.plugins,
                omEnabled: this.omEnabledInput(),
                omModel: this.omModelInput(),
                observeThreshold: this.observeThresholdInput(),
                reflectThreshold: this.reflectThresholdInput(),
            };
            setSetting('openrouter:config', orConfig);

            // Hot-reload Phoenix native backend with new credentials
            this.goChatService.updateConfig({
                apiKey: orConfig.apiKey,
                model: orConfig.model,
                temperature: orConfig.temperature,
                maxTokens: orConfig.maxTokens,
                reasoningEnabled: orConfig.reasoningEnabled,
                reasoningEffort: orConfig.reasoningEffort,
                reasoningMaxTokens: orConfig.reasoningMaxTokens,
                includeReasoning: orConfig.includeReasoning,
                structuredOutput: orConfig.structuredOutput,
                plugins: orConfig.plugins,
                omEnabled: orConfig.omEnabled,
                omModel: orConfig.omModel,
                observeThreshold: orConfig.observeThreshold,
                reflectThreshold: orConfig.reflectThreshold,
            });
        }

        // Save Google GenAI config
        if (this.googleApiKeyInput()) {
            this.googleGenAI.saveConfig({
                apiKey: this.googleApiKeyInput(),
                model: this.googleModelInput(),
                temperature: 0.7,
                maxOutputTokens: 2048,
                systemPrompt: this.systemPromptInput(),
            });
        }

        if (this.nvidiaApiKeyInput()) {
            this.nvidiaNim.saveConfig({
                apiKey: this.nvidiaApiKeyInput(),
                model: this.nvidiaModelInput(),
                temperature: this.nvidiaTemperatureInput(),
                topP: this.nvidiaTopPInput(),
                maxTokens: this.nvidiaMaxTokensInput(),
            });
        } else if (this.nvidiaNim.isConfigured()) {
            this.nvidiaNim.clearConfig();
        }

        setSetting('chat:systemPrompt', this.systemPromptInput());
        // console.log('[AiChatPanel] Settings saved, active provider:', this.activeProvider());
        this.showSettings.set(false);
    }

    getActiveProviderName(): string {
        if (this.activeProvider() === 'google' && this.googleGenAI.isConfigured()) {
            return `Google Gemini (${this.googleGenAI.getModel()})`;
        }
        if (this.activeProvider() === 'nvidia-nim' && this.nvidiaNim.isConfigured()) {
            return `NVIDIA NIM (${this.nvidiaNim.getModel().split('/').pop()})`;
        }
        const model = this.selectedModel();
        return model ? `Phoenix OpenRouter (${model.split('/').pop()})` : 'Phoenix OpenRouter';
    }

    toggleIndexMode(): void {
        this.indexEnabled.update(v => !v);
        setSetting('chat:indexMode', this.indexEnabled());
        console.log('[AiChatPanel] Index mode:', this.indexEnabled() ? 'ON' : 'OFF');
    }

    toggleSystemPrompt(): void {
        this.showSystemPrompt.update(v => !v);
    }

    resetSystemPrompt(): void {
        this.systemPromptInput.set(KAMMI_SYSTEM_PROMPT);
    }

    // -------------------------------------------------------------------------
    // Model Management
    // -------------------------------------------------------------------------

    private loadSavedModels(): string[] {
        const stored = getSetting<string[] | null>(this.MODELS_KEY, null);
        if (stored && stored.length > 0) return stored;
        // First run — persist seeds
        setSetting(this.MODELS_KEY, this.MODEL_SEEDS);
        return [...this.MODEL_SEEDS];
    }

    addCustomModel(): void {
        const id = this.customModelInput().trim();
        if (!id) return;
        const current = this.savedModels();
        if (current.includes(id)) {
            // Just select it if already present
            this.selectedModel.set(id);
            this.customModelInput.set('');
            return;
        }
        const updated = [id, ...current]; // Prepend so new models appear first
        this.savedModels.set(updated);
        setSetting(this.MODELS_KEY, updated);
        this.selectedModel.set(id);
        this.customModelInput.set('');
    }

    removeModel(id: string): void {
        const updated = this.savedModels().filter(m => m !== id);
        this.savedModels.set(updated);
        setSetting(this.MODELS_KEY, updated);
        // If the removed model was selected, fall back to first in list
        if (this.selectedModel() === id) {
            this.selectedModel.set(updated[0] ?? '');
        }
    }

    // -------------------------------------------------------------------------
    // History Panel
    // -------------------------------------------------------------------------

    openHistory(): void {
        this.loadSessions();
        this.showHistory.set(true);
    }

    private loadSessions(): void {
        // Get thread list from Phoenix native chat state
        const threads = this.goChatService.threads();

        // Build session info from threads
        const sessions: SessionInfo[] = threads.map((thread: Thread) => {
            return {
                id: thread.id,
                messageCount: 0, // Would require additional query
                createdAt: thread.created_at,
                preview: thread.title || undefined,
            };
        });

        this.sessions.set(sessions);
    }

    async selectSession(sessionId: string): Promise<void> {
        await this.goChatService.loadThread(sessionId);
        this.showHistory.set(false);
        this.currentTraceMsgId = null;
        this.activitySteps.set([]);
        this.pendingApprovals.set([]);
        this.currentRunId.set(null);
        this.approvalBusy.set(null);

        // Reload chat with new session messages
        this.restoreHistory();
    }

    formatSessionDate(timestamp: number): string {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now.getTime() - date.getTime();

        // Less than 1 day
        if (diff < 86400000) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        // Less than 7 days
        if (diff < 604800000) {
            return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
        }
        // Older
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }

    // -------------------------------------------------------------------------
    // QuikChat Setup
    // -------------------------------------------------------------------------

    private restoreHistory(): void {
        const storedMessages: DisplayMessage[] = this.goChatService.messages().map((m: any) => ({
            id: m.id || this.generateId(),
            content: m.content,
            role: m.role as 'user' | 'assistant' | 'system',
            timestamp: new Date(m.created_at || m.timestamp || Date.now()),
            isStreaming: !!m.is_streaming
        }));
        const traceMessages: DisplayMessage[] = this.displayMessages().filter((message) => message.role === 'system');
        const mergedMessages: DisplayMessage[] = [...storedMessages];
        for (const traceMessage of traceMessages) {
            const insertAt = mergedMessages.length > 0 ? mergedMessages.length - 1 : mergedMessages.length;
            mergedMessages.splice(insertAt, 0, traceMessage);
        }
        this.displayMessages.set(mergedMessages);
        this.scrollToBottom();
    }

    private generateId(): string {
        return Math.random().toString(36).substring(2, 11);
    }

    formatTime(date: Date): string {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    private scrollToBottom(): void {
        setTimeout(() => {
            if (this.messagesContainer) {
                const el = this.messagesContainer.nativeElement;
                el.scrollTop = el.scrollHeight;
            }
        }, 50);
    }

    async sendMessage(): Promise<void> {
        const text = this.currentMessage.trim();
        if (!text || this.isStreaming() || this.canvasRuns.busy() || (this.currentRunId() && this.pendingApprovals().length > 0)) return;

        if (this.aiMode() === 'canvas') {
            this.currentMessage = '';
            if (this.canvasIntent() === 'research') {
                await this.canvasRuns.startWorkspaceRun(text, 'side-panel', 'deep_research');
            } else if (this.canvasSelectionContext()?.text?.trim()) {
                await this.canvasRuns.startSelectionRun(text, undefined, 'side-panel');
            } else {
                await this.canvasRuns.startWorkspaceRun(text, 'side-panel');
            }
            this.scrollToBottom();
            return;
        }

        this.currentMessage = '';
        this.isStreaming.set(true);
        this.pendingApprovals.set([]);

        await this.goChatService.addUserMessage(text);
        this.scrollToBottom();

        const traceId = this.startActivityTrace();

        const googleConfigured = this.googleGenAI.isConfigured();
        const openRouterConfigured = this.isGoConfigured();
        const nvidiaConfigured = this.isNvidiaConfigured();

        if (!googleConfigured && !openRouterConfigured && !nvidiaConfigured) {
            this.finishActivityStep(traceId, 'error', 'AI provider is not configured.');
            this.displayMessages.update(msgs => [...msgs, {
                id: this.generateId(), content: '[Warning] Please configure an API key in settings to enable responses.', role: 'assistant', timestamp: new Date()
            }]);
            this.isStreaming.set(false);
            this.scrollToBottom();
            return;
        }

        const highlightedClips = this.chatContextClipStore.consumeAll();
        const highlightedContext = this.chatContextClipStore.formatForPrompt(highlightedClips);
        if (highlightedClips.length > 0) {
            this.addCompletedStep('tool', 'Using highlighted text', 'Injected highlighted note snippets.');
        }

        const appContext = await this.orchestrator.getAppContext();
        const runOptions = this.buildRunOptions(highlightedContext, appContext);
        const run = await this.goChatService.startRun(text, runOptions);
        if (!run) {
            this.finishActivityStep(traceId, 'error', 'Failed to start chat run.');
            this.isStreaming.set(false);
            return;
        }

        this.currentRunId.set(run.id);
        const snapshot = await this.waitForRunReady(run.id);
        if (!snapshot) {
            this.finishActivityStep(traceId, 'error', 'Run did not return a snapshot.');
            this.currentRunId.set(null);
            this.isStreaming.set(false);
            return;
        }

        if (snapshot.run.status === 'awaiting_approval') {
            this.finishActivityStep(traceId, 'done', 'Waiting for approval.');
            this.isStreaming.set(false);
            return;
        }

        if (snapshot.run.status === 'failed' || snapshot.run.status === 'cancelled') {
            this.finishActivityStep(traceId, 'error', snapshot.run.error || `Run ${snapshot.run.status}.`);
            this.currentRunId.set(null);
            this.isStreaming.set(false);
            return;
        }

        await this.streamPreparedRun(snapshot);
    }

    private async handleStreamingChat(
        runId: string,
        botMsgId: string,
        history: OpenRouterMessage[],
        systemPrompt: string,
        onProgress: (event: ChatProgressEvent) => void,
        onReasoning?: (chunk: string) => void
    ): Promise<void> {
        try {
            if (this.activeProvider() === 'google' && this.googleGenAI.isConfigured()) {
                const googleHistory: GoogleGenAIMessage[] = history
                    .filter((m: any) => m.role !== 'system')
                    .map((m: any) => ({
                        role: m.role === 'assistant' ? 'model' : 'user',
                        parts: [{ text: m.content || '' }]
                    }));

                await this.googleGenAI.streamChat(
                    googleHistory,
                    {
                        onChunk: (chunk: string) => {
                            if (onProgress) onProgress({ stage: 'stream', status: 'running' });
                            void this.goChatService.appendMessage(botMsgId, chunk);
                        },
                        onComplete: async (response: string) => {
                            if (onProgress) onProgress({ stage: 'stream', status: 'done', detail: 'Completed successfully.' });
                            await this.goChatService.updateMessage(botMsgId, response);
                            await this.goChatService.completeRun(runId, botMsgId, response);
                            this.currentBotMsgId = null;
                        },
                        onError: (err: any) => {
                            const errStr = err instanceof Error ? err.message : String(err);
                            if (onProgress) onProgress({ stage: 'stream', status: 'error', detail: errStr });
                            void this.goChatService.updateMessage(botMsgId, `Error: ${errStr}`);
                            void this.goChatService.completeRun(runId, botMsgId, '', errStr);
                            this.currentBotMsgId = null;
                        }
                    },
                    systemPrompt
                );
                return;
            }

            if (this.activeProvider() === 'nvidia-nim' && this.nvidiaNim.isConfigured()) {
                await this.nvidiaNim.streamChat(
                    history,
                    {
                        onChunk: (chunk: string) => {
                            if (onProgress) onProgress({ stage: 'stream', status: 'running' });
                            void this.goChatService.appendMessage(botMsgId, chunk);
                        },
                        onComplete: async (response: string) => {
                            if (onProgress) onProgress({ stage: 'stream', status: 'done', detail: 'Completed successfully.' });
                            await this.goChatService.updateMessage(botMsgId, response);
                            await this.goChatService.completeRun(runId, botMsgId, response);
                            this.currentBotMsgId = null;
                        },
                        onError: (err: Error) => {
                            const errStr = err.message;
                            if (onProgress) onProgress({ stage: 'stream', status: 'error', detail: errStr });
                            void this.goChatService.updateMessage(botMsgId, `Error: ${errStr}`);
                            void this.goChatService.completeRun(runId, botMsgId, '', errStr);
                            this.currentBotMsgId = null;
                        },
                        onEvent: onProgress,
                        onReasoningChunk: onReasoning,
                    },
                    systemPrompt
                );
                return;
            }

            // Otherwise, use openrouter (WASM)
            await this.goChatService.streamChat(
                history,
                {
                    onChunk: (chunk: string) => {
                        void this.goChatService.appendMessage(botMsgId, chunk);
                    },
                    onComplete: async (response: string) => {
                        await this.goChatService.updateMessage(botMsgId, response);
                        await this.goChatService.completeRun(runId, botMsgId, response);
                        this.currentBotMsgId = null;
                    },
                    onError: (err: any) => {
                        const errStr = err instanceof Error ? err.message : String(err);
                        void this.goChatService.updateMessage(botMsgId, `Error: ${errStr}`);
                        void this.goChatService.completeRun(runId, botMsgId, '', errStr);
                        this.currentBotMsgId = null;
                    },
                    onEvent: onProgress,
                    onReasoningChunk: onReasoning
                },
                systemPrompt
            );

        } catch (err: unknown) {
            console.error('[AiChatPanel] Error calling provider:', err);
            const errStr = err instanceof Error ? err.message : String(err);
            if (onProgress) {
                onProgress({ stage: 'stream', status: 'error', detail: errStr });
            }
            void this.goChatService.updateMessage(botMsgId, `System Error: ${errStr}`);
            void this.goChatService.completeRun(runId, botMsgId, '', errStr);
            this.currentBotMsgId = null;
        }
    }

    private buildRunOptions(highlightedContext: string, appContext: any): RunOptions {
        const currentThread = this.goChatService.currentThread() as any;
        const narrativeId = appContext?.narrativeId || currentThread?.narrativeId || currentThread?.narrative_id || '';
        const folderId = appContext?.folderId || '';
        const canvasMode = this.aiMode() === 'canvas';
        const workspaceEnabled = this.indexEnabled() || canvasMode;
        const plannerEnabled = workspaceEnabled && this.isGoConfigured();

        const externalParts: string[] = [];
        if (appContext?.activeNoteTitle || appContext?.activeNoteSnippet) {
            externalParts.push(
                `Active note: ${appContext.activeNoteTitle || appContext.activeNoteId || 'Untitled'}\n${appContext.activeNoteSnippet || ''}`.trim()
            );
        }
        if (highlightedContext) {
            externalParts.push(highlightedContext);
        }
        if (canvasMode) {
            const liveSelection = this.workspace.getSelection();
            externalParts.push(
                `Canvas mode is enabled for the currently open note. The assistant may inspect the note, highlight candidate ranges, and use proposal tools for edits.`
            );
            if (liveSelection && !liveSelection.empty) {
                externalParts.push(
                    `Live editor selection range=${liveSelection.from}-${liveSelection.to}\n${liveSelection.text}`.trim()
                );
            }
        }

        return {
            finalProvider: this.activeProvider(),
            finalModel: this.getActiveModelForProvider(),
            plannerModel: this.selectedModel(),
            omModel: this.omModelInput(),
            plannerEnabled,
            omEnabled: this.omEnabledInput(),
            workspaceEnabled,
            mutationsEnabled: canvasMode,
            deadlineMs: 8000,
            mutationPolicy: 'confirm',
            narrativeId,
            folderId,
            scopeId: narrativeId,
            baseSystemPrompt: this.buildBaseSystemPrompt(),
            initialExternalContext: externalParts.join('\n\n'),
        };
    }

    private buildBaseSystemPrompt(): string {
        if (this.aiMode() !== 'canvas') {
            return this.systemPromptInput();
        }

        return `${this.systemPromptInput().trim()}

Canvas mode is enabled.
- You are working against the currently open note in the editor.
- You may inspect the active note, inspect the current selection, and highlight candidate ranges before editing.
- Proposal tools create diffs or save actions that may require approval; never assume a proposal has already been applied.
- Prefer focused edits tied to the user's request over broad rewrites.
- After edits are approved/applied, describe what changed clearly.`;
    }

    private getActiveModelForProvider(): string {
        switch (this.activeProvider()) {
            case 'google':
                return this.googleModelInput();
            case 'nvidia-nim':
                return this.nvidiaModelInput();
            case 'go-openrouter':
            default:
                return this.selectedModel();
        }
    }

    private async waitForRunReady(runId: string): Promise<ChatRunSnapshot | null> {
        for (let attempt = 0; attempt < 80; attempt++) {
            const snapshot = await this.goChatService.pollRun(runId);
            if (!snapshot) return null;

            this.pendingApprovals.set((snapshot.approvals || []).filter((approval) => approval.status === 'pending'));
            this.syncRunTrace(snapshot);

            switch (snapshot.run.status) {
                case 'awaiting_tool_host': {
                    const pendingCalls = (snapshot.toolCalls || []).filter((call) => call.host === 'typescript' && call.status === 'pending_host');
                    if (pendingCalls.length === 0) {
                        await this.sleep(200);
                        continue;
                    }

                    const submissions = await Promise.all(pendingCalls.map((call) => this.toolHost.executeCall(call)));
                    const afterSubmit = await this.goChatService.submitToolResults(runId, submissions);
                    if (!afterSubmit) return snapshot;

                    this.pendingApprovals.set((afterSubmit.approvals || []).filter((approval) => approval.status === 'pending'));
                    this.syncRunTrace(afterSubmit);

                    if (afterSubmit.run.status === 'planning') {
                        await this.goChatService.resumeRun(runId);
                    }
                    if (afterSubmit.run.status === 'awaiting_approval' || afterSubmit.run.status === 'ready_to_answer' || afterSubmit.run.status === 'degraded' || afterSubmit.run.status === 'failed' || afterSubmit.run.status === 'cancelled') {
                        return afterSubmit;
                    }
                    await this.sleep(150);
                    continue;
                }
                case 'queued':
                case 'gathering':
                case 'executing_tools':
                case 'streaming':
                    await this.sleep(200);
                    continue;
                case 'planning':
                    await this.goChatService.processPlannerRun(runId);
                    await this.sleep(100);
                    continue;
                default:
                    return snapshot;
            }
        }

        return this.goChatService.pollRun(runId);
    }

    private async streamPreparedRun(snapshot: ChatRunSnapshot): Promise<void> {
        const runId = snapshot.run.id;
        const history = this.buildConversationHistory();
        const reasoningStepId = this.activeProvider() !== 'google' && this.reasoningEnabledInput()
            ? this.addActivityStep('reasoning', 'Reasoning', 'Waiting for model reasoning...')
            : null;

        const streamingMessage = await this.goChatService.startStreamingMessage();
        if (!streamingMessage) {
            this.isStreaming.set(false);
            this.currentRunId.set(null);
            return;
        }

        await this.goChatService.markRunStreaming(runId, streamingMessage.id);

        const streamStepId = this.addActivityStep('stream', 'Responding', 'Writing the answer...');
        await this.handleStreamingChat(
            runId,
            streamingMessage.id,
            history,
            snapshot.run.preparedSystemPrompt || this.systemPromptInput(),
            (event) => this.applyProgressEvent(streamStepId, event),
            reasoningStepId ? (chunk) => this.appendActivityStepDetail(reasoningStepId, chunk) : undefined
        );

        if (reasoningStepId) this.finalizeReasoningStep(reasoningStepId);
        this.finishActivityStep(streamStepId, 'done', 'Done');
        this.pendingApprovals.set([]);
        this.currentRunId.set(null);
        this.isStreaming.set(false);
        this.scrollToBottom();
    }

    async handleApprovalDecision(approval: ChatApprovalRequest, approved: boolean): Promise<void> {
        const runId = this.currentRunId();
        if (!runId) return;

        this.approvalBusy.set(approval.id);
        try {
            const decisionJSON = approved
                ? await this.toolHost.applyApproval(approval, true)
                : JSON.stringify({ approved: false, applied: false, reason: 'User rejected proposal.' });

            const snapshot = await this.goChatService.submitApproval(runId, approval.id, approved, decisionJSON);
            if (!snapshot) return;

            this.pendingApprovals.set((snapshot.approvals || []).filter((item) => item.status === 'pending'));
            this.syncRunTrace(snapshot);

            if (snapshot.run.status === 'planning') {
                await this.goChatService.resumeRun(runId);
                const resumed = await this.waitForRunReady(runId);
                if (!resumed) return;
                if (resumed.run.status === 'awaiting_approval') {
                    this.isStreaming.set(false);
                    return;
                }
                if (resumed.run.status === 'ready_to_answer' || resumed.run.status === 'degraded') {
                    this.isStreaming.set(true);
                    await this.streamPreparedRun(resumed);
                }
            }
        } finally {
            this.approvalBusy.set(null);
        }
    }

    private syncRunTrace(snapshot: ChatRunSnapshot): void {
        const steps: ActivityTraceStep[] = (snapshot.events || []).map((event) => ({
            id: event.id,
            kind: event.kind === 'tool' ? 'tool' : 'status',
            label: event.label,
            detail: event.detail || undefined,
            status: event.status === 'error' ? 'error' : event.status === 'running' ? 'running' : 'done',
            latencyMs: event.latencyMs,
        }));
        this.activitySteps.set(steps);
        this.syncActivityTrace();
    }

    private sleep(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    private buildConversationHistory(): OpenRouterMessage[] {
        return this.goChatService.messages()
            .slice(-10)
            .filter(m => m.role === 'user' || m.role === 'assistant')
            .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }));
    }

    private startActivityTrace(): string {
        this.traceCounter = 0;
        this.traceStartedAt.clear();
        this.activitySteps.set([]);
        const traceMsgId = this.generateId();
        this.currentTraceMsgId = traceMsgId;
        this.displayMessages.update(msgs => [...msgs, {
            id: traceMsgId,
            content: '',
            role: 'system',
            timestamp: new Date(),
            activitySteps: [],
            statusText: 'Starting'
        }]);
        this.scrollToBottom();
        return this.addActivityStep(
            'reasoning',
            'Thinking',
            this.reasoningEnabledInput() && this.activeProvider() !== 'google'
                ? 'Reasoning through your request...'
                : 'Reading your request...'
        );
    }

    private addActivityStep(
        kind: ActivityTraceStep['kind'],
        label: string,
        detail?: string
    ): string {
        const id = `step-${++this.traceCounter}`;
        this.traceStartedAt.set(id, Date.now());
        this.activitySteps.update((steps) => [...steps, { id, kind, label, detail, status: 'running' }]);
        this.syncActivityTrace();
        return id;
    }

    private addCompletedStep(
        kind: ActivityTraceStep['kind'],
        label: string,
        detail?: string,
        status: 'done' | 'error' = 'done',
        latencyMs?: number
    ): void {
        const id = `step-${++this.traceCounter}`;
        this.activitySteps.update((steps) => [...steps, { id, kind, label, detail, status, latencyMs }]);
        this.syncActivityTrace();
    }
    private finishActivityStep(
        id: string,
        status: ActivityTraceStep['status'],
        detail?: string,
        latencyMs?: number
    ): void {
        const startedAt = this.traceStartedAt.get(id);
        const measuredLatency = latencyMs ?? (startedAt ? Date.now() - startedAt : undefined);
        this.traceStartedAt.delete(id);

        this.activitySteps.update((steps) =>
            steps.map((step) => {
                if (step.id !== id) return step;
                return {
                    ...step,
                    status,
                    detail: detail ?? step.detail,
                    latencyMs: measuredLatency,
                };
            })
        );
        this.syncActivityTrace();
    }

    private appendActivityStepDetail(stepId: string, chunk: string): void {
        this.activitySteps.update((steps) =>
            steps.map((step) => {
                if (step.id !== stepId) return step;
                const nextDetail = step.detail === 'Waiting for model reasoning...'
                    ? chunk
                    : `${step.detail || ''}${chunk}`;
                return {
                    ...step,
                    detail: nextDetail,
                };
            })
        );
        this.syncActivityTrace();
    }
    private finalizeReasoningStep(stepId: string): void {
        const step = this.activitySteps().find((item) => item.id === stepId);
        if (!step) return;
        const detail = step.detail === 'Waiting for model reasoning...'
            ? 'Reasoning was enabled, but the model did not return reasoning tokens.'
            : step.detail;
        this.finishActivityStep(stepId, 'done', detail);
    }
    private applyProgressEvent(stepId: string, event: ChatProgressEvent): void {
        if (event.status === 'running') {
            this.activitySteps.update((steps) =>
                steps.map((step) => {
                    if (step.id !== stepId) return step;
                    return {
                        ...step,
                        detail: event.detail ?? step.detail,
                    };
                })
            );
            this.syncActivityTrace();
            return;
        }

        this.finishActivityStep(stepId, event.status, event.detail);
    }

    private syncActivityTrace(): void {
        const id = this.currentTraceMsgId;
        if (!id) return;
        const currentSteps = [...this.activitySteps()];
        const statusText = this.getActivityStatusText();
        this.displayMessages.update(msgs =>
            msgs.map(m => m.id === id ? { ...m, activitySteps: currentSteps, statusText } : m)
        );
        this.scrollToBottom();
    }

    private getActivityStatusText(): string {
        const steps = this.activitySteps();
        if (steps.length === 0) return 'Starting';

        for (let i = steps.length - 1; i >= 0; i--) {
            if (steps[i].status === 'running') return steps[i].label;
        }

        return steps.some((step) => step.status === 'error') ? 'Completed with issues' : 'Done';
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    private toErrorMessage(err: unknown): string {
        return err instanceof Error ? err.message : String(err);
    }

    // -------------------------------------------------------------------------
    // Public Actions
    // -------------------------------------------------------------------------

    async newSession(): Promise<void> {
        await this.goChatService.newSession();
        this.currentTraceMsgId = null;
        this.activitySteps.set([]);
        this.pendingApprovals.set([]);
        this.currentRunId.set(null);
        this.approvalBusy.set(null);
        this.displayMessages.set([]);
        this.restoreHistory();
    }

    async clearChat(): Promise<void> {
        await this.goChatService.clearThread();
        this.currentTraceMsgId = null;
        this.activitySteps.set([]);
        this.pendingApprovals.set([]);
        this.currentRunId.set(null);
        this.approvalBusy.set(null);
        this.displayMessages.set([]);
        this.restoreHistory();
    }

    async exportChat(): Promise<void> {
        const json = await this.goChatService.exportThread();
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const threadId = this.goChatService.currentThread()?.id || 'unknown';
        a.download = `chat-${threadId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }
}







