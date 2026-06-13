import { CommonModule } from '@angular/common';
import { Component, Input, OnChanges, computed, signal } from '@angular/core';
import { Activity, AlertTriangle, CheckCircle2, Clock3, Database, Gauge, Search, X } from 'lucide-angular';
import { LucideAngularModule } from 'lucide-angular';

import type { GraphIndexRunReceipt, GraphRebuildSnapshot } from '../../../../graph-rebuild/graph-rebuild-snapshot';
import {
    buildGraphEvaluationDashboard,
    type GraphEvaluationCategoryId,
    type GraphEvaluationMetric,
    type GraphEvaluationTone,
} from './graph-evaluation-dashboard';

@Component({
    selector: 'app-graph-evaluation-dashboard',
    standalone: true,
    imports: [CommonModule, LucideAngularModule],
    templateUrl: './graph-evaluation-dashboard.component.html',
    styleUrl: './graph-evaluation-dashboard.component.css',
})
export class GraphEvaluationDashboardComponent implements OnChanges {
    @Input() snapshot: GraphRebuildSnapshot | null = null;
    @Input() receipt: GraphIndexRunReceipt | null = null;
    @Input() stale = false;

    readonly dashboard = signal(buildGraphEvaluationDashboard(null, null));
    readonly category = signal<GraphEvaluationCategoryId | 'all'>('all');
    readonly selectedMetricId = signal('');
    readonly selectedMetric = computed(() => this.dashboard().metricsById[this.selectedMetricId()] || null);
    readonly visibleMetrics = computed(() => {
        const category = this.category();
        return category === 'all' ? this.dashboard().metrics : this.dashboard().metrics.filter((metric) => metric.categoryId === category);
    });

    readonly ActivityIcon = Activity;
    readonly AlertIcon = AlertTriangle;
    readonly CheckIcon = CheckCircle2;
    readonly ClockIcon = Clock3;
    readonly DatabaseIcon = Database;
    readonly GaugeIcon = Gauge;
    readonly SearchIcon = Search;
    readonly XIcon = X;

    ngOnChanges(): void {
        const next = buildGraphEvaluationDashboard(this.snapshot, this.receipt);
        this.dashboard.set(next);
        const current = this.selectedMetricId();
        if (current && !next.metricsById[current]) this.selectedMetricId.set('');
    }

    selectCategory(category: GraphEvaluationCategoryId | 'all'): void {
        this.category.set(category);
        const selected = this.selectedMetric();
        if (selected && category !== 'all' && selected.categoryId !== category) this.selectedMetricId.set('');
    }

    inspect(metric: GraphEvaluationMetric): void {
        this.selectedMetricId.set(metric.id);
    }

    closeInspector(): void {
        this.selectedMetricId.set('');
    }

    toneClass(tone: GraphEvaluationTone): string {
        return `evaluation-tone-${tone}`;
    }

    scoreLabel(score: number | null): string {
        return score === null ? '--' : String(score);
    }

    durationLabel(): string {
        const durationMs = this.dashboard().durationMs;
        if (durationMs === null) return '--';
        return durationMs < 1000 ? `${Math.round(durationMs)} ms` : `${(durationMs / 1000).toFixed(1)} s`;
    }

    distributionWidth(metric: GraphEvaluationMetric, value: number): number {
        const max = Math.max(1, ...(metric.distribution || []).map((row) => row.value));
        return Math.max(value ? 6 : 0, Math.round(value / max * 100));
    }
}
