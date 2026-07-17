/**
 * AI Chat Page Component
 *
 * Full-feature chat page that sits between sidebars (like Graph/Calendar pages).
 * Uses @neurodevworks/angular-chatbot types + the Phoenix chat/GoogleGenAI services.
 */

import { Component, OnInit, OnDestroy, ViewChild, ElementRef, signal, computed, inject, effect, untracked, AfterViewInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
    LucideAngularModule,
    ArrowLeft,
    Plus,
    Trash2,
    Download,
    Settings,
    Send,
    History,
    Database,
    Brain,
    RotateCcw,
    Bot,
    User,
    Sparkles,
    MessageCircle,
    X,
} from 'lucide-angular';
import { getSetting, setSetting } from '../../lib/dexie/settings.service';
import {
    type Thread,
    type ChatConfig,
    type ChatProgressEvent,
    type OpenRouterMessage,
} from '../../lib/services/phoenix-chat.service';
import {
    GoogleGenAIService,
    GoogleGenAIMessage,
} from '../../lib/services/google-genai.service';
import { ChatContextClipStore } from '../../lib/store/chat-context-clip.store';
import { KammiChatUiService } from '../../lib/services/kammi-chat-ui.service';
import { CanvasRunInspectorComponent } from '../../lib/components/canvas-run-inspector.component';
import { CanvasAgentRunService } from '../../lib/services/canvas-agent-run.service';

// Re-export types from the installed package for compatibility
import type { ChatMessage, ChatOptions, ChatConfig as PkgChatConfig } from '@neurodevworks/angular-chatbot';

interface SessionInfo {
    id: string;
    messageCount: number;
    createdAt: number;
    preview?: string;
}

interface DisplayMessage {
    id: string;
    content: string;
    role: 'user' | 'assistant' | 'system';
    timestamp: Date;
    isStreaming?: boolean;
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
    selector: 'app-ai-chat-page',
    standalone: true,
    imports: [CommonModule, FormsModule, LucideAngularModule, CanvasRunInspectorComponent],
    template: `
        <div class="h-full flex flex-col bg-background text-foreground">
            <!-- Top Toolbar -->
            <div class="flex items-center gap-4 px-4 py-2 border-b border-white/10 bg-gradient-to-b from-zinc-800 to-zinc-950 shrink-0">
                <button
                    (click)="navigateToEditor()"
                    class="flex items-center gap-2 px-3 py-1.5 text-sm rounded-md text-slate-300 hover:text-white hover:bg-white/10 transition-colors">
                    <lucide-icon [img]="ArrowLeft" size="16"></lucide-icon>
                    Back to Editor
                </button>

                <div class="flex-1 text-center">
                    <h1 class="text-lg font-semibold text-white/90 flex items-center justify-center gap-2">
                        <lucide-icon [img]="BotIcon" size="20" class="text-teal-400"></lucide-icon>
                        Kammi AI Chat
                    </h1>
                    <p class="text-xs text-slate-500">{{ getActiveProviderName() }}</p>
                </div>

                <div class="flex items-center gap-1">
                    <button
                        (click)="newSession()"
                        class="p-2 rounded-md text-slate-400 hover:text-teal-400 hover:bg-teal-500/10 transition-colors"
                        title="New Chat">
                        <lucide-icon [img]="PlusIcon" size="16"></lucide-icon>
                    </button>
                    <button
                        (click)="toggleHistory()"
                        class="p-2 rounded-md transition-colors"
                        [class.text-teal-400]="showHistory()"
                        [class.bg-teal-500/10]="showHistory()"
                        [class.text-slate-400]="!showHistory()"
                        [class.hover:text-white]="!showHistory()"
                        [class.hover:bg-white/10]="!showHistory()"
                        title="Chat History">
                        <lucide-icon [img]="HistoryIcon" size="16"></lucide-icon>
                    </button>
                    <button
                        (click)="exportChat()"
                        class="p-2 rounded-md text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
                        title="Export Chat">
                        <lucide-icon [img]="DownloadIcon" size="16"></lucide-icon>
                    </button>
                    <button
                        (click)="clearChat()"
                        class="p-2 rounded-md text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="Clear Chat">
                        <lucide-icon [img]="Trash2Icon" size="16"></lucide-icon>
                    </button>
                    <div class="w-px h-5 bg-white/10 mx-1"></div>
                    <button
                        (click)="toggleSettings()"
                        class="p-2 rounded-md transition-colors"
                        [class.bg-teal-500/20]="showSettings()"
                        [class.text-teal-400]="showSettings()"
                        [class.text-slate-400]="!showSettings()"
                        [class.hover:text-white]="!showSettings()"
                        [class.hover:bg-white/10]="!showSettings()"
                        title="Settings">
                        <lucide-icon [img]="SettingsIcon" size="16"></lucide-icon>
                    </button>
                </div>
            </div>

            <app-canvas-run-inspector />

            <!-- Main Content -->
            <div class="flex-1 flex overflow-hidden relative">
                <!-- History Panel (left overlay) -->
                @if (showHistory()) {
                    <div class="w-72 border-r border-border bg-sidebar overflow-y-auto shrink-0 flex flex-col">
                        <div class="p-3 border-b border-white/10 flex items-center justify-between">
                            <span class="text-sm font-semibold text-white">Threads</span>
                            <button class="p-1 rounded text-slate-400 hover:text-white" (click)="showHistory.set(false)">
                                <lucide-icon [img]="XIcon" size="14"></lucide-icon>
                            </button>
                        </div>
                        <div class="flex-1 overflow-y-auto p-2 space-y-1.5">
                            @for (session of sessions(); track session.id) {
                                <button
                                    class="w-full p-3 text-left rounded-lg border transition-all text-sm"
                                    [class.border-teal-500]="session.id === goChatService.currentThread()?.id"
                                    [class.bg-teal-500/10]="session.id === goChatService.currentThread()?.id"
                                    [class.border-white/5]="session.id !== goChatService.currentThread()?.id"
                                    [class.hover:bg-white/5]="session.id !== goChatService.currentThread()?.id"
                                    (click)="selectSession(session.id)">
                                    <div class="flex items-center justify-between">
                                        <span class="text-xs font-medium text-white truncate">{{ session.id }}</span>
                                        <span class="text-[10px] text-slate-500">{{ session.messageCount }} msgs</span>
                                    </div>
                                    <div class="text-[10px] text-slate-500 mt-1">{{ formatSessionDate(session.createdAt) }}</div>
                                    @if (session.preview) {
                                        <div class="text-xs text-slate-500 mt-1 truncate italic">"{{ session.preview }}"</div>
                                    }
                                </button>
                            } @empty {
                                <div class="text-center py-12 text-slate-500">
                                    <lucide-icon [img]="HistoryIcon" size="32" class="mx-auto opacity-30 mb-2"></lucide-icon>
                                    <p class="text-xs">No chat history yet</p>
                                </div>
                            }
                        </div>
                    </div>
                }

                <!-- Chat Area -->
                <div class="flex-1 flex flex-col min-w-0">
                    <!-- Messages -->
                    <div #messagesContainer class="flex-1 overflow-y-auto px-4 py-6 space-y-6 custom-scrollbar">
                        @if (displayMessages().length === 0) {
                            <div class="flex flex-col items-center justify-center h-full text-center">
                                <div class="w-20 h-20 rounded-2xl bg-teal-500/10 flex items-center justify-center mb-6 border border-teal-500/20">
                                    <lucide-icon [img]="SparklesIcon" size="36" class="text-teal-400"></lucide-icon>
                                </div>
                                <h2 class="text-xl font-semibold text-white mb-2">Kammi AI</h2>
                                <p class="text-sm text-slate-400 max-w-md">
                                    Your creative world-building assistant. Ask about characters, lore, story structure, or anything else!
                                </p>
                                <div class="grid grid-cols-2 gap-2 mt-6 max-w-lg">
                                    @for (suggestion of suggestions; track suggestion) {
                                        <button
                                            class="p-3 text-left text-xs rounded-lg border border-white/5 bg-white/[0.02] hover:bg-teal-500/10 hover:border-teal-500/20 text-slate-400 hover:text-slate-200 transition-all"
                                            (click)="sendSuggestion(suggestion)">
                                            {{ suggestion }}
                                        </button>
                                    }
                                </div>
                            </div>
                        }

                        @for (msg of displayMessages(); track msg.id) {
                            @if (msg.role === 'system' && msg.activitySteps) {
                                <div class="inline-trace max-w-3xl mx-auto w-full">
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
                                <div class="flex gap-3 max-w-3xl mx-auto w-full" [class.flex-row-reverse]="msg.role === 'user'">
                                    <div class="w-8 h-8 rounded-lg shrink-0 flex items-center justify-center border"
                                        [class.bg-teal-500/20]="msg.role === 'assistant'"
                                        [class.border-teal-500/30]="msg.role === 'assistant'"
                                        [class.bg-zinc-800]="msg.role === 'user'"
                                        [class.border-zinc-700]="msg.role === 'user'">
                                        <lucide-icon
                                            [img]="msg.role === 'user' ? UserIcon : BotIcon"
                                            size="16"
                                            [class.text-teal-400]="msg.role === 'assistant'"
                                            [class.text-zinc-400]="msg.role === 'user'">
                                        </lucide-icon>
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center gap-2 mb-1" [class.justify-end]="msg.role === 'user'">
                                            <span class="text-xs font-medium" [class.text-teal-400]="msg.role === 'assistant'" [class.text-zinc-400]="msg.role === 'user'">
                                                {{ msg.role === 'user' ? 'You' : 'Kammi' }}
                                            </span>
                                            <span class="text-[10px] text-slate-600">{{ formatTime(msg.timestamp) }}</span>
                                        </div>
                                        <div class="message-bubble px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap"
                                            [class.user-bubble]="msg.role === 'user'"
                                            [class.assistant-bubble]="msg.role === 'assistant'">
                                            {{ msg.content }}
                                            @if (msg.isStreaming) {
                                                <span class="inline-flex gap-1 ml-1 align-middle">
                                                    <span class="w-1.5 h-1.5 rounded-full bg-teal-400 animate-bounce" style="animation-delay: 0ms"></span>
                                                    <span class="w-1.5 h-1.5 rounded-full bg-teal-400 animate-bounce" style="animation-delay: 150ms"></span>
                                                    <span class="w-1.5 h-1.5 rounded-full bg-teal-400 animate-bounce" style="animation-delay: 300ms"></span>
                                                </span>
                                            }
                                        </div>
                                    </div>
                                </div>
                            }
                        }
                    </div>

                    <!-- Input Area -->
                    <div class="shrink-0 border-t border-border px-4 py-4 chat-input-area">
                        <div class="max-w-3xl mx-auto flex items-end gap-3">
                            <div class="flex-1 relative">
                                <textarea
                                    #messageInput
                                    class="w-full px-4 py-3 pr-12 text-sm rounded-xl border border-zinc-700 bg-zinc-900 text-white placeholder:text-slate-500 focus:outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500/30 resize-none transition-all"
                                    [placeholder]="researchToNote() ? 'Deep research a question and write the verified report to the open note...' : 'Ask Kammi anything...'"
                                    [(ngModel)]="currentMessage"
                                    (keydown.enter)="onEnterKey($event)"
                                    [disabled]="isStreaming()"
                                    rows="1"
                                    style="max-height: 150px"
                                ></textarea>
                            </div>
                            <button
                                class="shrink-0 w-11 h-11 rounded-xl flex items-center justify-center transition-all send-btn"
                                [class.active]="currentMessage.trim() && !isStreaming()"
                                [disabled]="!currentMessage.trim() || isStreaming()"
                                (click)="sendMessage()">
                                <lucide-icon [img]="SendIcon" size="18"></lucide-icon>
                            </button>
                        </div>
                        <div class="max-w-3xl mx-auto mt-2 flex items-center gap-3">
                            <div class="flex items-center gap-1.5">
                                <button
                                    class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors"
                                    [class.bg-teal-600]="indexEnabled()"
                                    [class.text-white]="indexEnabled()"
                                    [class.text-slate-500]="!indexEnabled()"
                                    [class.hover:text-slate-300]="!indexEnabled()"
                                    (click)="toggleIndexMode()">
                                    <lucide-icon [img]="DatabaseIcon" size="10"></lucide-icon>
                                    Index {{ indexEnabled() ? 'ON' : 'OFF' }}
                                </button>
                                <button
                                    class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors"
                                    [class.bg-amber-500]="researchToNote()"
                                    [class.text-black]="researchToNote()"
                                    [class.text-slate-500]="!researchToNote()"
                                    (click)="toggleResearchToNote()">
                                    <lucide-icon [img]="BrainIcon" size="10"></lucide-icon>
                                    Research to note {{ researchToNote() ? 'ON' : 'OFF' }}
                                </button>
                            </div>
                            <span class="text-[10px] text-slate-600">{{ goChatService.messageCount() }} messages in thread</span>
                        </div>
                    </div>
                </div>

                <!-- Settings Panel (right) -->
                @if (showSettings()) {
                    <div class="w-80 border-l border-border bg-sidebar overflow-y-auto shrink-0 custom-scrollbar">
                        <div class="p-4 space-y-5">
                            <div class="flex items-center justify-between">
                                <h3 class="text-sm font-semibold text-white">Settings</h3>
                                <button class="p-1 rounded text-slate-400 hover:text-white" (click)="showSettings.set(false)">
                                    <lucide-icon [img]="XIcon" size="14"></lucide-icon>
                                </button>
                            </div>

                            <!-- Provider Tabs -->
                            <div class="flex gap-1 p-1 bg-white/5 rounded-lg">
                                <button
                                    class="flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                                    [class.bg-teal-600]="activeProvider() === 'google'"
                                    [class.text-white]="activeProvider() === 'google'"
                                    [class.text-slate-400]="activeProvider() !== 'google'"
                                    (click)="activeProvider.set('google')">
                                    Google Gemini
                                </button>
                                <button
                                    class="flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                                    [class.bg-teal-600]="activeProvider() === 'go-openrouter'"
                                    [class.text-white]="activeProvider() === 'go-openrouter'"
                                    [class.text-slate-400]="activeProvider() !== 'go-openrouter'"
                                    (click)="activeProvider.set('go-openrouter')">
                                    OpenRouter (Phoenix)
                                </button>
                                <button
                                    class="flex-1 px-3 py-1.5 text-xs font-medium rounded-md transition-colors"
                                    [class.bg-teal-600]="activeProvider() === 'nvidia-nim'"
                                    [class.text-white]="activeProvider() === 'nvidia-nim'"
                                    [class.text-slate-400]="activeProvider() !== 'nvidia-nim'"
                                    (click)="activeProvider.set('nvidia-nim')">
                                    NVIDIA NIM
                                </button>
                            </div>

                            <!-- Google Settings -->
                            @if (activeProvider() === 'google') {
                                <div class="space-y-3">
                                    <div class="space-y-1">
                                        <label class="text-xs font-medium text-slate-400">Google AI API Key</label>
                                        <input type="password"
                                            class="settings-input"
                                            placeholder="AIza..."
                                            [value]="googleApiKeyInput()"
                                            (input)="googleApiKeyInput.set($any($event.target).value)" />
                                    </div>
                                    <div class="space-y-1">
                                        <label class="text-xs font-medium text-slate-400">Model</label>
                                        <select class="settings-input"
                                            [value]="googleModelInput()"
                                            (change)="googleModelInput.set($any($event.target).value)">
                                            @for (model of googleGenAI.availableModels; track model.id) {
                                                <option [value]="model.id">{{ model.name }}</option>
                                            }
                                        </select>
                                    </div>
                                </div>
                            }

                            <!-- OpenRouter Settings -->
                            @if (activeProvider() === 'go-openrouter') {
                                <div class="space-y-3">
                                    <div class="space-y-1">
                                        <label class="text-xs font-medium text-slate-400">OpenRouter API Key</label>
                                        <input type="password"
                                            class="settings-input"
                                            placeholder="sk-or-..."
                                            [value]="apiKeyInput()"
                                            (input)="apiKeyInput.set($any($event.target).value)" />
                                    </div>
                                    <div class="space-y-2">
                                        <label class="text-xs font-medium text-slate-400">Model</label>
                                        <div class="px-2 py-1.5 bg-teal-900/30 border border-teal-500/30 rounded-md">
                                            <span class="text-xs text-teal-300 font-mono truncate block">{{ selectedModel() || 'None' }}</span>
                                        </div>
                                        <div class="flex gap-1">
                                            <input type="text"
                                                class="settings-input flex-1 !text-xs font-mono"
                                                placeholder="provider/model-id"
                                                [value]="customModelInput()"
                                                (input)="customModelInput.set($any($event.target).value)"
                                                (keydown.enter)="addCustomModel()" />
                                            <button class="shrink-0 px-2 py-1.5 text-xs bg-teal-600 hover:bg-teal-500 text-white rounded-md transition-colors disabled:opacity-40"
                                                [disabled]="!customModelInput().trim()"
                                                (click)="addCustomModel()">Add</button>
                                        </div>
                                        <div class="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
                                            @for (model of savedModels(); track model) {
                                                <div class="group flex items-center gap-0.5 pl-2 pr-1 py-0.5 rounded-full text-[10px] font-mono cursor-pointer border transition-colors"
                                                    [class.bg-teal-600]="selectedModel() === model"
                                                    [class.text-white]="selectedModel() === model"
                                                    [class.border-teal-500]="selectedModel() === model"
                                                    [class.bg-white/5]="selectedModel() !== model"
                                                    [class.text-slate-400]="selectedModel() !== model"
                                                    [class.border-white/10]="selectedModel() !== model"
                                                    (click)="selectedModel.set(model)">
                                                    <span class="max-w-[140px] truncate">{{ model }}</span>
                                                    <button class="ml-0.5 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
                                                        (click)="$event.stopPropagation(); removeModel(model)">&times;</button>
                                                </div>
                                            }
                                        </div>
                                    </div>
                                    <div class="grid grid-cols-2 gap-3">
                                        <div class="space-y-1">
                                            <label class="text-[10px] text-slate-400 flex justify-between"><span>Temperature</span><span>{{ temperatureInput() }}</span></label>
                                            <input type="range" min="0" max="2" step="0.1" class="w-full accent-teal-500"
                                                [value]="temperatureInput()" (input)="temperatureInput.set(+$any($event.target).value)" />
                                        </div>
                                        <div class="space-y-1">
                                            <label class="text-[10px] text-slate-400 flex justify-between"><span>Max Tokens</span><span>{{ maxTokensInput() }}</span></label>
                                            <input type="range" min="256" max="131072" step="256" class="w-full accent-teal-500"
                                                [value]="maxTokensInput()" (input)="maxTokensInput.set(+$any($event.target).value)" />
                                        </div>
                                    </div>

                                    <!-- Reasoning -->
                                    <div class="p-2 rounded-md border border-teal-500/20 bg-teal-950/20 space-y-2">
                                        <div class="flex items-center justify-between">
                                            <label class="text-xs font-medium">Reasoning</label>
                                            <button class="relative w-10 h-5 rounded-full transition-colors"
                                                [class.bg-teal-600]="reasoningEnabledInput()"
                                                [class.bg-white/10]="!reasoningEnabledInput()"
                                                (click)="reasoningEnabledInput.set(!reasoningEnabledInput())">
                                                <span class="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"
                                                    [class.translate-x-5]="reasoningEnabledInput()"></span>
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            }

                            <!-- NVIDIA NIM Settings -->
                            @if (activeProvider() === 'nvidia-nim') {
                                <div class="space-y-3">
                                    <div class="space-y-1">
                                        <label class="text-xs font-medium text-slate-400">NVIDIA API Key</label>
                                        <input type="password"
                                            class="settings-input"
                                            placeholder="nvapi-..."
                                            [value]="nvidiaApiKeyInput()"
                                            (input)="nvidiaApiKeyInput.set($any($event.target).value)" />
                                    </div>
                                    <div class="space-y-1">
                                        <label class="text-xs font-medium text-slate-400">Model</label>
                                        <select class="settings-input"
                                            [value]="nvidiaModelInput()"
                                            (change)="nvidiaModelInput.set($any($event.target).value)">
                                            @for (model of nvidiaNim.availableModels; track model.id) {
                                                <option [value]="model.id">{{ model.name }}</option>
                                            }
                                        </select>
                                    </div>
                                    <div class="grid grid-cols-2 gap-3">
                                        <div class="space-y-1">
                                            <label class="text-[10px] text-slate-400 flex justify-between"><span>Temperature</span><span>{{ nvidiaTemperatureInput() }}</span></label>
                                            <input type="range" min="0" max="2" step="0.1" class="w-full accent-teal-500"
                                                [value]="nvidiaTemperatureInput()" (input)="nvidiaTemperatureInput.set(+$any($event.target).value)" />
                                        </div>
                                        <div class="space-y-1">
                                            <label class="text-[10px] text-slate-400 flex justify-between"><span>Top P</span><span>{{ nvidiaTopPInput() }}</span></label>
                                            <input type="range" min="0.1" max="1" step="0.05" class="w-full accent-teal-500"
                                                [value]="nvidiaTopPInput()" (input)="nvidiaTopPInput.set(+$any($event.target).value)" />
                                        </div>
                                    </div>
                                    <div class="space-y-1">
                                        <label class="text-[10px] text-slate-400 flex justify-between"><span>Max Tokens</span><span>{{ nvidiaMaxTokensInput() }}</span></label>
                                        <input type="range" min="512" max="32768" step="512" class="w-full accent-teal-500"
                                            [value]="nvidiaMaxTokensInput()" (input)="nvidiaMaxTokensInput.set(+$any($event.target).value)" />
                                    </div>
                                </div>
                            }

                            <!-- Observational Memory -->
                            <div class="p-3 rounded-lg border border-teal-500/20 bg-teal-950/10 space-y-3">
                                <div class="flex items-center justify-between gap-3">
                                    <div>
                                        <label class="text-xs font-medium text-slate-200">Observational Memory</label>
                                        <p class="text-[10px] text-slate-400">Keep observer and reflector agents available for shared thread memory.</p>
                                    </div>
                                    <button class="relative w-10 h-5 rounded-full transition-colors"
                                        [class.bg-teal-600]="omEnabledInput()"
                                        [class.bg-white/10]="!omEnabledInput()"
                                        (click)="omEnabledInput.set(!omEnabledInput())">
                                        <span class="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow-sm"
                                            [class.translate-x-5]="omEnabledInput()"></span>
                                    </button>
                                </div>

                                @if (omEnabledInput()) {
                                    <div class="space-y-3">
                                        <div class="space-y-1">
                                            <label class="text-xs font-medium text-slate-400">OM Model</label>
                                            <input type="text"
                                                class="settings-input"
                                                placeholder="provider/model-id"
                                                [value]="omModelInput()"
                                                (input)="omModelInput.set($any($event.target).value)" />
                                        </div>
                                        <div class="grid grid-cols-2 gap-3">
                                            <div class="space-y-1">
                                                <label class="text-[10px] text-slate-400 flex justify-between"><span>Observe Threshold</span><span>{{ observeThresholdInput() }}</span></label>
                                                <input type="range" min="100" max="10000" step="100" class="w-full accent-teal-500"
                                                    [value]="observeThresholdInput()" (input)="observeThresholdInput.set(+$any($event.target).value)" />
                                            </div>
                                            <div class="space-y-1">
                                                <label class="text-[10px] text-slate-400 flex justify-between"><span>Reflect Threshold</span><span>{{ reflectThresholdInput() }}</span></label>
                                                <input type="range" min="500" max="20000" step="100" class="w-full accent-teal-500"
                                                    [value]="reflectThresholdInput()" (input)="reflectThresholdInput.set(+$any($event.target).value)" />
                                            </div>
                                        </div>
                                    </div>
                                }
                            </div>

                            <!-- System Prompt -->
                            <div class="space-y-2">
                                <div class="flex items-center justify-between">
                                    <label class="text-xs font-medium text-slate-300">Custom Instructions</label>
                                    <button class="text-[10px] text-slate-500 hover:text-teal-400" (click)="resetSystemPrompt()">
                                        <lucide-icon [img]="RotateCcwIcon" size="10" class="inline mr-0.5"></lucide-icon>Reset
                                    </button>
                                </div>
                                <textarea class="settings-input !h-28 resize-none text-xs leading-relaxed"
                                    [value]="systemPromptInput()"
                                    (input)="systemPromptInput.set($any($event.target).value)"
                                    placeholder="System instructions..."></textarea>
                            </div>

                            <!-- Save -->
                            <div class="flex gap-2">
                                <button class="flex-1 px-3 py-2 text-xs font-medium bg-teal-600 hover:bg-teal-500 text-white rounded-md transition-colors"
                                    (click)="saveSettings()">Save Settings</button>
                            </div>
                        </div>
                    </div>
                }
            </div>
        </div>
    `,
    styles: [`
        :host { display: block; height: 100%; }

        .chat-input-area {
            background: linear-gradient(to top,
                rgba(17, 94, 89, 0.08) 0%,
                transparent 100%
            );
        }

        .user-bubble {
            background: #27272a;
            border: 1px solid #3f3f46;
            color: #f4f4f5;
        }

        .assistant-bubble {
            background: rgba(255, 255, 255, 0.03);
            border-left: 2px solid rgba(20, 184, 166, 0.4);
            border-radius: 0 16px 16px 0 !important;
            color: #cbd5e1;
        }

        .send-btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #64748b;
            cursor: not-allowed;
        }

        .send-btn.active {
            background: linear-gradient(135deg, #115e59 0%, #134e4a 50%, #0f2a2e 100%);
            border-color: rgba(20, 184, 166, 0.4);
            color: #e2e8f0;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(17, 94, 89, 0.4);
        }

        .send-btn.active:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(17, 94, 89, 0.5);
        }

        .settings-input {
            width: 100%;
            padding: 8px 12px;
            font-size: 13px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            color: #e2e8f0;
            outline: none;
            transition: border-color 0.2s;
        }

        .settings-input:focus {
            border-color: #14b8a6;
            box-shadow: 0 0 0 2px rgba(20, 184, 166, 0.15);
        }

        .inline-trace {
            display: grid;
            gap: 10px;
        }

        .inline-trace-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
        }

        .inline-trace-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #67e8f9;
        }

        .brain-mark {
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

        .inline-trace-status {
            font-size: 11px;
            color: #94a3b8;
        }

        .inline-trace-steps {
            display: grid;
            gap: 8px;
        }

        .inline-trace-step {
            display: grid;
            grid-template-columns: 10px 1fr auto;
            gap: 8px;
            align-items: start;
            padding: 10px 12px;
            border: 1px solid rgba(39, 39, 42, 0.9);
            border-radius: 14px;
            background: rgba(9, 9, 11, 0.52);
        }

        .inline-trace-dot {
            width: 8px;
            height: 8px;
            margin-top: 4px;
            border-radius: 9999px;
            background: rgba(20, 184, 166, 0.55);
        }

        .inline-trace-step.done .inline-trace-dot {
            background: #2dd4bf;
        }

        .inline-trace-step.error .inline-trace-dot {
            background: #f87171;
        }

        .inline-trace-step-title {
            font-size: 12px;
            font-weight: 600;
            color: #f8fafc;
        }

        .inline-trace-step-detail {
            margin-top: 3px;
            font-size: 12px;
            line-height: 1.5;
            color: #94a3b8;
            white-space: pre-wrap;
        }

        .inline-trace-step-latency {
            font-size: 11px;
            color: #64748b;
        }

        .custom-scrollbar {
            scrollbar-width: thin;
            scrollbar-color: rgba(20, 184, 166, 0.2) transparent;
        }

        .custom-scrollbar::-webkit-scrollbar { width: 6px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background-color: rgba(20, 184, 166, 0.2); border-radius: 3px; }
    `]
})
export class AiChatPageComponent implements OnInit, OnDestroy, AfterViewInit {
    @ViewChild('messagesContainer') messagesContainer!: ElementRef<HTMLDivElement>;
    @ViewChild('messageInput') messageInput!: ElementRef<HTMLTextAreaElement>;

    private router = inject(Router);
    private readonly chatUi = inject(KammiChatUiService);
    goChatService = this.chatUi.goChatService;
    googleGenAI = this.chatUi.googleGenAI;
    nvidiaNim = this.chatUi.nvidiaNim;

    // Icons
    readonly ArrowLeft = ArrowLeft;
    readonly PlusIcon = Plus;
    readonly Trash2Icon = Trash2;
    readonly DownloadIcon = Download;
    readonly SettingsIcon = Settings;
    readonly SendIcon = Send;
    readonly HistoryIcon = History;
    readonly DatabaseIcon = Database;
    readonly BrainIcon = Brain;
    readonly RotateCcwIcon = RotateCcw;
    readonly BotIcon = Bot;
    readonly UserIcon = User;
    readonly SparklesIcon = Sparkles;
    readonly MessageCircleIcon = MessageCircle;
    readonly XIcon = X;

    // UI state
    showSettings = signal(false);
    showHistory = signal(false);
    isStreaming = this.chatUi.isStreaming;
    currentMessage = '';

    // Provider
    activeProvider = this.chatUi.activeProvider;

    // OpenRouter settings
    apiKeyInput = this.chatUi.apiKeyInput;
    selectedModel = this.chatUi.selectedModel;
    temperatureInput = this.chatUi.temperatureInput;
    maxTokensInput = this.chatUi.maxTokensInput;
    reasoningEnabledInput = this.chatUi.reasoningEnabledInput;
    reasoningEffortInput = this.chatUi.reasoningEffortInput;
    reasoningMaxTokensInput = this.chatUi.reasoningMaxTokensInput;
    omEnabledInput = this.chatUi.omEnabledInput;

    // OM Settings
    omModelInput = this.chatUi.omModelInput;
    observeThresholdInput = this.chatUi.observeThresholdInput;
    reflectThresholdInput = this.chatUi.reflectThresholdInput;

    // Google settings
    googleApiKeyInput = this.chatUi.googleApiKeyInput;
    googleModelInput = this.chatUi.googleModelInput;

    // NVIDIA NIM settings
    nvidiaApiKeyInput = this.chatUi.nvidiaApiKeyInput;
    nvidiaModelInput = this.chatUi.nvidiaModelInput;
    nvidiaTemperatureInput = this.chatUi.nvidiaTemperatureInput;
    nvidiaTopPInput = this.chatUi.nvidiaTopPInput;
    nvidiaMaxTokensInput = this.chatUi.nvidiaMaxTokensInput;

    // System prompt
    systemPromptInput = this.chatUi.systemPromptInput;

    // Index mode
    indexEnabled = this.chatUi.indexEnabled;
    readonly researchToNote = signal(false);
    readonly canvasRuns = inject(CanvasAgentRunService);

    // Models
    savedModels = this.chatUi.savedModels;
    customModelInput = this.chatUi.customModelInput;

    // History
    sessions = this.chatUi.sessions;

    // Display messages synced locally during streaming, globally when thread changes
    displayMessages = this.chatUi.displayMessages;

    // Suggestions
    readonly suggestions = [
        '✨ Help me develop a character backstory',
        '🗺️ Create a magic system for my world',
        '📖 Outline a three-act story structure',
        '🏰 Describe a fantasy city in detail',
    ];

    readonly isGoConfigured = this.chatUi.isGoConfigured;

    constructor() {
        effect(() => {
            this.displayMessages();
            this.isStreaming();
            this.scrollToBottom();
        });
    }

    ngOnInit(): void {
        void this.chatUi.init();
    }

    ngAfterViewInit(): void {
        this.scrollToBottom();
    }

    ngOnDestroy(): void {}

    // ---- Navigation ----
    navigateToEditor(): void {
        this.router.navigate(['/']);
    }

    // ---- Settings ----
    private loadSettings(): void {
        void this.chatUi.init();
    }

    toggleSettings(): void { this.showSettings.update(v => !v); }

    async saveSettings(): Promise<void> {
        await this.chatUi.saveSettings();
        this.showSettings.set(false);
    }

    resetSystemPrompt(): void { this.chatUi.resetSystemPrompt(); }

    getActiveProviderName(): string {
        return this.chatUi.getActiveProviderName();
    }

    toggleIndexMode(): void {
        this.chatUi.toggleIndexMode();
    }

    toggleResearchToNote(): void {
        this.researchToNote.update(value => !value);
    }

    // ---- Models ----
    private loadSavedModels(): string[] {
        return this.savedModels();
    }

    addCustomModel(): void {
        this.chatUi.addCustomModel();
    }

    removeModel(id: string): void {
        this.chatUi.removeModel(id);
    }

    // ---- Go Chat Service ----
    private async initPhoenixChatService(): Promise<void> {
        await this.chatUi.init();
    }

    // ---- History ----
    toggleHistory(): void {
        this.showHistory.update(v => !v);
    }

    private loadSessions(): void {
        return;
    }

    async selectSession(sessionId: string): Promise<void> {
        await this.chatUi.selectSession(sessionId);
        this.showHistory.set(false);
    }

    formatSessionDate(timestamp: number): string {
        return this.chatUi.formatSessionDate(timestamp);
    }

    // ---- Messages ----
    
    private restoreHistory(): void {
        return;
    }

    sendSuggestion(text: string): void {
        const clean = this.chatUi.stripSuggestionPrefix(text);
        this.currentMessage = clean;
        void this.sendMessage();
    }

    onEnterKey(event: Event): void {
        const kbEvent = event as KeyboardEvent;
        if (kbEvent.shiftKey) return; // Allow shift+enter for newlines
        kbEvent.preventDefault();
        void this.sendMessage();
    }

    async sendMessage(): Promise<void> {
        const text = this.currentMessage;
        if (!text.trim()) return;
        this.currentMessage = '';
        if (this.researchToNote()) {
            await this.canvasRuns.startWorkspaceRun(text, 'ai-page', 'deep_research');
            return;
        }
        await this.chatUi.sendMessage(text);
    }

    private async streamResponse(
        botMsg: DisplayMessage,
        history: OpenRouterMessage[],
        systemPrompt: string,
    ): Promise<void> {
        void botMsg;
        void history;
        void systemPrompt;
    }

    private buildConversationHistory(): OpenRouterMessage[] {
        return [];
    }

    private addBotMessage(content: string): void {
        void content;
    }

    // ---- Actions ----
    async newSession(): Promise<void> {
        await this.chatUi.newSession();
    }

    async clearChat(): Promise<void> {
        await this.chatUi.clearChat();
    }

    async exportChat(): Promise<void> {
        const { json, threadId } = await this.chatUi.exportCurrentThread();
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat-${threadId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    // ---- Helpers ----
    formatTime(date: Date): string {
        return this.chatUi.formatTime(date);
    }

    private scrollToBottom(): void {
        setTimeout(() => {
            if (this.messagesContainer) {
                const el = this.messagesContainer.nativeElement;
                el.scrollTop = el.scrollHeight;
            }
        }, 50);
    }

    private generateId(): string {
        return Math.random().toString(36).substring(2, 11);
    }
}
