import { Injectable, inject } from '@angular/core';

import { PhoenixBackendService } from './phoenix-backend.service';
import { EditorService, type EditorSnapshot } from './editor.service';
import type {
    PhoenixDocumentIndexReadRequest,
    PhoenixDocumentIndexReadResponse,
} from './phoenix-document-index.model';

export interface EditorDocumentIndexNote {
    id: string;
    title?: string | null;
    markdownContent?: string | null;
}

export type EditorDocumentIndexReadOptions = Omit<
    Partial<PhoenixDocumentIndexReadRequest>,
    'documentId' | 'noteId' | 'title' | 'text'
>;

@Injectable({ providedIn: 'root' })
export class EditorDocumentIndexService {
    private readonly editor = inject(EditorService);
    private readonly phoenix = inject(PhoenixBackendService);

    async readCurrentNote(
        note: EditorDocumentIndexNote,
        options: EditorDocumentIndexReadOptions = {},
    ): Promise<PhoenixDocumentIndexReadResponse> {
        const snapshot = this.editor.captureSnapshot('api');
        return this.phoenix.readDocumentIndex(
            editorDocumentIndexReadRequest(note, snapshot, options),
        );
    }
}

export function editorDocumentIndexReadRequest(
    note: EditorDocumentIndexNote,
    snapshot: EditorSnapshot | null,
    options: EditorDocumentIndexReadOptions = {},
): PhoenixDocumentIndexReadRequest {
    return {
        documentId: note.id,
        noteId: note.id,
        title: note.title || note.id,
        text: snapshot?.markdown ?? note.markdownContent ?? '',
        ...options,
    };
}
