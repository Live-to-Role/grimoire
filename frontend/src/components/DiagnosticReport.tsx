import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Stethoscope, Copy, Check, Download, AlertCircle, AlertTriangle, Info, Loader2 } from 'lucide-react';
import apiClient from '../api/client';

interface Problem {
  severity: 'error' | 'warning' | 'info';
  code: string;
  message: string;
  hint?: string;
}

interface WorkerInfo {
  heartbeat: string | null;
  seconds_since_heartbeat: number | null;
  running: boolean;
  paused: boolean;
}

interface WatchedFolderInfo {
  path: string;
  label: string | null;
  enabled: boolean;
  exists: boolean;
  readable: boolean;
  product_count: number;
  last_scanned_at: string | null;
}

export interface Diagnostics {
  generated_at: string;
  app: { version: string };
  system: {
    python_version: string;
    platform: string;
    machine: string;
    cpu_count: number | null;
    in_container: boolean;
    total_memory_mb: number | null;
    data_disk_free_mb: number | null;
  };
  database: { product_count: number };
  worker: WorkerInfo;
  queue: {
    pending: number;
    processing: number;
    completed: number;
    failed: number;
    pending_by_type: Record<string, number>;
    oldest_pending_age_seconds: number | null;
    stuck_processing: number;
    recent_errors: {
      task_type: string;
      error_message: string;
      completed_at: string | null;
      product_id: number;
    }[];
  };
  library: { watched_folders: WatchedFolderInfo[] };
  ai: {
    ollama_base_url: string;
    ollama_reachable: boolean | null;
    ollama_models: string[];
    openai_key_set: boolean;
    anthropic_key_set: boolean;
  };
  config: Record<string, unknown>;
  problems: Problem[];
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return 'never';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

/**
 * Render the report as the markdown we want pasted into a bug report: the
 * detected problems first, then enough context to act on them without a
 * follow-up round trip.
 */
export function formatReport(d: Diagnostics): string {
  const lines: string[] = [];

  lines.push('## Grimoire diagnostic report');
  lines.push('');
  lines.push(`- Generated: ${d.generated_at}`);
  lines.push(`- Version: ${d.app.version}`);
  lines.push(`- Platform: ${d.system.platform} (${d.system.machine})`);
  lines.push(
    `- CPUs: ${d.system.cpu_count ?? 'unknown'} · RAM: ${
      d.system.total_memory_mb ? `${Math.round(d.system.total_memory_mb / 1024)} GB` : 'unknown'
    } · Docker: ${d.system.in_container ? 'yes' : 'no'}`,
  );
  lines.push('');

  lines.push('### Problems detected');
  if (d.problems.length === 0) {
    lines.push('None.');
  } else {
    for (const p of d.problems) {
      lines.push(`- **[${p.severity}] ${p.message}**`);
      if (p.hint) lines.push(`  - ${p.hint}`);
    }
  }
  lines.push('');

  lines.push('### Worker');
  lines.push(`- Running: ${d.worker.running ? 'yes' : 'no'}`);
  lines.push(`- Paused: ${d.worker.paused ? 'yes (Grimoire Paused)' : 'no (Grimoire Working)'}`);
  lines.push(`- Last heartbeat: ${d.worker.heartbeat ?? 'never'} (${formatAge(d.worker.seconds_since_heartbeat)})`);
  lines.push('');

  lines.push('### Queue');
  lines.push(
    `- pending ${d.queue.pending} · processing ${d.queue.processing} · completed ${d.queue.completed} · failed ${d.queue.failed}`,
  );
  const byType = Object.entries(d.queue.pending_by_type);
  if (byType.length) {
    lines.push(`- Pending by type: ${byType.map(([k, v]) => `${k}=${v}`).join(', ')}`);
  }
  lines.push(`- Oldest pending: ${formatAge(d.queue.oldest_pending_age_seconds)}`);
  if (d.queue.recent_errors.length) {
    lines.push('- Recent errors:');
    for (const e of d.queue.recent_errors) {
      lines.push(`  - ${e.task_type} (product ${e.product_id}): ${e.error_message}`);
    }
  }
  lines.push('');

  lines.push('### Library');
  lines.push(`- Products: ${d.database.product_count}`);
  if (d.library.watched_folders.length === 0) {
    lines.push('- No watched folders configured.');
  } else {
    for (const f of d.library.watched_folders) {
      lines.push(
        `- ${f.path} — ${f.exists ? 'exists' : 'MISSING'}, ${
          f.readable ? 'readable' : 'NOT READABLE'
        }, ${f.enabled ? 'enabled' : 'disabled'}, ${f.product_count} products`,
      );
    }
  }
  lines.push('');

  lines.push('### AI');
  lines.push(
    `- Ollama ${d.ai.ollama_base_url}: ${
      d.ai.ollama_reachable === null ? 'not checked' : d.ai.ollama_reachable ? 'reachable' : 'UNREACHABLE'
    }`,
  );
  if (d.ai.ollama_models.length) lines.push(`- Models: ${d.ai.ollama_models.join(', ')}`);
  lines.push(`- OpenAI key set: ${d.ai.openai_key_set ? 'yes' : 'no'}`);
  lines.push(`- Anthropic key set: ${d.ai.anthropic_key_set ? 'yes' : 'no'}`);
  lines.push('');

  lines.push('<details><summary>Full report (JSON)</summary>');
  lines.push('');
  lines.push('```json');
  lines.push(JSON.stringify(d, null, 2));
  lines.push('```');
  lines.push('');
  lines.push('</details>');

  return lines.join('\n');
}

const SEVERITY_STYLE = {
  error: { icon: AlertCircle, color: '#dc2626', background: 'rgba(220, 38, 38, 0.08)' },
  warning: { icon: AlertTriangle, color: '#d97706', background: 'rgba(217, 119, 6, 0.08)' },
  info: { icon: Info, color: 'var(--color-accent)', background: 'var(--color-accent-light)' },
} as const;

/**
 * "Generate Diagnostic Report" — one button that answers "why is nothing
 * happening?" without asking the user to read logs or run docker commands.
 */
export function DiagnosticReport() {
  const [report, setReport] = useState<Diagnostics | null>(null);
  const [copied, setCopied] = useState(false);

  const generate = useMutation<Diagnostics, Error, void>({
    mutationFn: async () => {
      const res = await apiClient.get<Diagnostics>('/health/diagnostics');
      return res.data;
    },
    onSuccess: (data) => {
      setReport(data);
      setCopied(false);
    },
  });

  const copyReport = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(formatReport(report));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const downloadReport = () => {
    if (!report) return;
    const blob = new Blob([formatReport(report)], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `grimoire-diagnostics-${report.generated_at.slice(0, 19).replace(/[:T]/g, '')}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section
      className="rounded-lg p-6"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <div className="mb-4 flex items-start gap-3">
        <Stethoscope className="mt-1 h-5 w-5" style={{ color: 'var(--color-accent)' }} />
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Diagnostics
          </h2>
          <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
            Check whether processing is actually running, and produce a report you can send with a
            bug report. API keys are never included.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => generate.mutate()}
          disabled={generate.isPending}
          className="flex items-center gap-2 rounded-lg px-4 py-2 text-base font-medium text-white disabled:opacity-50"
          style={{ backgroundColor: 'var(--color-accent)', minHeight: '44px' }}
        >
          {generate.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Stethoscope className="h-4 w-4" />
          )}
          Generate Diagnostic Report
        </button>

        {report && (
          <>
            <button
              onClick={() => void copyReport()}
              className="flex items-center gap-2 rounded-lg border px-4 py-2 text-base font-medium"
              style={{
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-secondary)',
                minHeight: '44px',
              }}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button
              onClick={downloadReport}
              className="flex items-center gap-2 rounded-lg border px-4 py-2 text-base font-medium"
              style={{
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-secondary)',
                minHeight: '44px',
              }}
            >
              <Download className="h-4 w-4" />
              Download
            </button>
          </>
        )}
      </div>

      {generate.isError && (
        <p className="mt-4 text-base" style={{ color: '#dc2626' }}>
          Could not reach the Grimoire API: {generate.error.message}
        </p>
      )}

      {report && (
        <div className="mt-6 space-y-4">
          {report.problems.length === 0 ? (
            <div
              className="flex items-center gap-2 rounded-lg p-3 text-base"
              style={{ backgroundColor: 'var(--color-accent-light)', color: 'var(--color-accent)' }}
            >
              <Check className="h-4 w-4" />
              No problems detected.
            </div>
          ) : (
            <div className="space-y-2">
              {report.problems.map((problem) => {
                const style = SEVERITY_STYLE[problem.severity] ?? SEVERITY_STYLE.info;
                const Icon = style.icon;
                return (
                  <div
                    key={problem.code + problem.message}
                    className="flex gap-3 rounded-lg p-3"
                    style={{ backgroundColor: style.background }}
                  >
                    <Icon className="mt-0.5 h-4 w-4 flex-shrink-0" style={{ color: style.color }} />
                    <div className="min-w-0">
                      <p className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>
                        {problem.message}
                      </p>
                      {problem.hint && (
                        <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                          {problem.hint}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              {
                label: 'Worker',
                value: report.worker.running
                  ? report.worker.paused
                    ? 'Paused'
                    : 'Working'
                  : 'Not running',
              },
              { label: 'Pending', value: String(report.queue.pending) },
              { label: 'Failed', value: String(report.queue.failed) },
              {
                label: 'Ollama',
                value:
                  report.ai.ollama_reachable === null
                    ? 'Not checked'
                    : report.ai.ollama_reachable
                      ? 'Reachable'
                      : 'Unreachable',
              },
            ].map((stat) => (
              <div
                key={stat.label}
                className="rounded-lg p-3"
                style={{ border: '1px solid var(--color-border)' }}
              >
                <dt className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  {stat.label}
                </dt>
                <dd className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  {stat.value}
                </dd>
              </div>
            ))}
          </dl>

          <details>
            <summary
              className="cursor-pointer text-base font-medium"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              Full report
            </summary>
            <pre
              className="mt-2 max-h-96 overflow-auto rounded-lg p-3 text-xs"
              style={{
                backgroundColor: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              {formatReport(report)}
            </pre>
          </details>
        </div>
      )}
    </section>
  );
}
