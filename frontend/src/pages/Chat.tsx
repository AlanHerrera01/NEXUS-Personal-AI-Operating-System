import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useAgentsDialog } from '../hooks/useAgentsDialog';
import { useAsyncData } from '../hooks/useAsyncData';
import { useI18n } from '../hooks/useI18n';
import { useOverview } from '../hooks/useOverview';
import { agentApi } from '../services/api/agentApi';
import { catalogApi } from '../services/api/catalogApi';
import { conversationApi } from '../services/api/conversationApi';
import { permissionsApi } from '../services/api/permissionsApi';
import { ApiError, ApiNetworkError } from '../services/api/apiClient';
import type { InterpolationValues, MessageKey } from '../i18n/types';
import type { AgentActionResponse, AgentRunResponse, PermissionRequest } from '../types';

/** The translator, shaped so helpers outside the component can take it as an argument. */
type Translate = (key: MessageKey, values?: InterpolationValues) => string;

/* A shortcut is the operator's own words: it is dropped into the input and sent
   to the agent, so both its label and its text follow the interface language.
   Keep the keys here and translate where the chips are rendered. */
const QUICK_CHIPS: MessageKey[] = [
  'pages.chat.chips.plan',
  'pages.chat.chips.search',
  'pages.chat.chips.run',
  'pages.chat.chips.explain',
];

interface Turn {
  id: number;
  prompt: string;
  createdAt: number;
  state: 'running' | 'done' | 'error';
  run?: AgentRunResponse;
  error?: string;
}

interface RecentRun {
  runId: string;
  label: string;
  status: string;
  /** Backend timestamp shown as a relative age; null for a run from this conversation. */
  updatedAt: string | null;
}

function errorText(caught: unknown, t: Translate): string {
  if (caught instanceof ApiNetworkError) return caught.message;
  if (caught instanceof ApiError) return caught.message;
  if (caught instanceof Error) return caught.message;
  return t('pages.chat.errors.runFailed');
}

function runTone(status: string): string {
  if (status === 'COMPLETED') return 'text-tertiary';
  if (status === 'WAITING_PERMISSION') return 'text-error';
  if (status === 'FAILED' || status === 'BLOCKED' || status === 'CANCELLED') return 'text-error';
  return 'text-secondary';
}

function stepTone(status: string): string {
  if (status === 'COMPLETED' || status === 'APPROVED') return 'text-tertiary';
  if (status === 'FAILED' || status === 'BLOCKED') return 'text-error';
  if (status === 'EXECUTING') return 'text-secondary';
  return 'text-outline';
}

function stepBadgeTone(status: string): string {
  if (status === 'COMPLETED' || status === 'APPROVED') return 'bg-tertiary/20 text-tertiary';
  if (status === 'FAILED' || status === 'BLOCKED') return 'bg-error/20 text-error';
  if (status === 'EXECUTING') return 'bg-secondary/20 text-secondary animate-pulse';
  return 'bg-surface-container-high text-outline';
}

function stepIcon(status: string): string {
  if (status === 'COMPLETED' || status === 'APPROVED') return 'check';
  if (status === 'FAILED') return 'close';
  if (status === 'BLOCKED') return 'block';
  if (status === 'EXECUTING') return 'sync';
  return 'schedule';
}

/** The sentence under a plan step; the key travels here, the text is rendered. */
function actionNarrative(status: string): MessageKey {
  switch (status) {
    case 'PROPOSED':
      return 'pages.chat.action.proposed';
    case 'APPROVED':
      return 'pages.chat.action.approved';
    case 'EXECUTING':
      return 'pages.chat.action.executing';
    case 'COMPLETED':
      return 'pages.chat.action.completed';
    case 'FAILED':
      return 'pages.chat.action.failed';
    case 'BLOCKED':
      return 'pages.chat.action.blocked';
    default:
      return 'pages.chat.action.unknown';
  }
}

/** The agent's own account of where the run stands right now. */
function runNarrative(run: AgentRunResponse, t: Translate): string {
  switch (run.status) {
    case 'CREATED':
    case 'CONTEXT_LOADING':
      return t('pages.chat.run.narrative.context');
    case 'PLANNING':
      return t('pages.chat.run.narrative.planning');
    case 'EXECUTING':
    case 'OBSERVING':
      return t('pages.chat.run.narrative.executing');
    case 'WAITING_PERMISSION':
      return t('pages.chat.run.narrative.waitingPermission');
    case 'COMPLETED':
      return run.response ?? t('pages.chat.run.narrative.completed');
    case 'FAILED':
      return run.response ?? t('pages.chat.run.narrative.failed');
    case 'BLOCKED':
      return run.response ?? t('pages.chat.run.narrative.blocked');
    case 'CANCELLED':
      return t('pages.chat.run.narrative.cancelled');
    default:
      return run.response ?? t('pages.chat.run.narrative.unknown');
  }
}

function summarize(args: Record<string, unknown>, max = 72): string {
  const text = JSON.stringify(args);
  if (!text) return '{}';
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Strip the markdown fence a model sometimes wraps around its JSON decision. */
function unwrapFence(text: string): string {
  const trimmed = text.trim();
  if (!trimmed.startsWith('```')) return trimmed;
  return trimmed
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/```\s*$/, '')
    .trim();
}

const JSON_ESCAPES: Record<string, string> = {
  n: '\n',
  r: '\r',
  t: '\t',
  '"': '"',
  '\\': '\\',
  '/': '/',
  b: '\b',
  f: '\f',
};

/**
 * Decode a JSON string that may contain raw newlines or bare quotes. The model
 * usually escapes them, but a quoted phrase inside the prose ("gear fear") can
 * arrive unescaped; that makes the envelope invalid JSON while the text remains
 * unambiguous.
 */
function decodeJsonString(raw: string): string {
  let result = '';
  for (let index = 0; index < raw.length; index += 1) {
    const character = raw[index];
    if (character !== '\\') {
      result += character;
      continue;
    }
    const following = raw[index + 1];
    if (following === undefined) {
      result += '\\';
      break;
    }
    if (following === 'u') {
      const digits = raw.slice(index + 2, index + 6);
      if (/^[0-9a-fA-F]{4}$/.test(digits)) {
        result += String.fromCharCode(parseInt(digits, 16));
        index += 5;
        continue;
      }
    }
    result += JSON_ESCAPES[following] ?? following;
    index += 1;
  }
  return result;
}

/** Take the whole response field, even when its prose contains bare quotes. */
function recoverFinalResponse(candidate: string): string | null {
  const decision = /"decision"\s*:\s*"FINAL"/i.exec(candidate);
  if (!decision) return null;
  const field = /"response"\s*:\s*"/.exec(candidate.slice(decision.index + decision[0].length));
  if (!field) return null;
  const start = decision.index + decision[0].length + field.index + field[0].length;
  const end = candidate.lastIndexOf('}');
  if (end <= start) return null;
  const body = candidate.slice(start, end);
  const closing = body.lastIndexOf('"');
  if (closing === -1) return null;
  const recovered = decodeJsonString(body.slice(0, closing)).trim();
  return recovered || null;
}

/**
 * Some models wrap the answer in the decision envelope despite being told not
 * to. The run stores what the model returned, so legacy runs and a malformed
 * reply would otherwise show the JSON to the operator. Recover the prose when
 * the envelope names a FINAL decision; leave every other text untouched.
 */
function cleanAgentResponse(text: string | null | undefined): string {
  if (!text) return '';
  const candidate = unwrapFence(text);
  if (!candidate.startsWith('{')) return text;

  try {
    const parsed: unknown = JSON.parse(candidate);
    if (parsed && typeof parsed === 'object') {
      const record = parsed as Record<string, unknown>;
      if (
        String(record.decision ?? '').toUpperCase() === 'FINAL' &&
        typeof record.response === 'string'
      ) {
        return record.response;
      }
    }
  } catch {
    // The envelope may be invalid JSON because of literal newlines. The
    // targeted extraction below still recovers the response field.
  }

  if (!/"decision"\s*:\s*"FINAL"/i.test(candidate)) return text;
  return recoverFinalResponse(candidate) ?? text;
}

const INLINE_MARKDOWN =
  /(\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|_[^_\n]+_|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;

/** Bold, italic, inline code and links; no HTML is ever injected. */
function inlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = new RegExp(INLINE_MARKDOWN.source, 'g');
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith('**') || token.startsWith('__')) {
      nodes.push(
        <strong key={key++} className="font-semibold text-on-surface">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith('`')) {
      nodes.push(
        <code key={key++} className="px-1 py-0.5 rounded bg-surface-container-highest font-code-base text-code-base text-on-surface">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith('[')) {
      const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(token);
      if (link) {
        nodes.push(
          <a
            key={key++}
            href={link[2]}
            target="_blank"
            rel="noreferrer noopener"
            className="text-secondary underline decoration-secondary/40 hover:decoration-secondary"
          >
            {link[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    } else {
      nodes.push(
        <em key={key++} className="italic text-on-surface-variant">
          {token.slice(1, -1)}
        </em>,
      );
    }
    last = pattern.lastIndex;
  }

  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function isBlockStart(line: string): boolean {
  const trimmed = line.trim();
  return (
    trimmed.startsWith('```') ||
    /^#{1,3}\s+/.test(trimmed) ||
    /^[-*]\s+/.test(trimmed) ||
    /^\d+[.)]\s+/.test(trimmed) ||
    trimmed.startsWith('> ') ||
    /^---+$/.test(trimmed) ||
    /^\*\*[^*].*\*\*$/.test(trimmed)
  );
}

/**
 * A deliberately small markdown renderer for agent prose. It covers what the
 * model actually emits -- headings, lists, emphasis, links, code -- and builds
 * React elements, so untrusted text never becomes HTML.
 */
function MarkdownText({ text, className = '' }: { text: string; className?: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (trimmed === '') {
      index += 1;
      continue;
    }

    if (trimmed.startsWith('```')) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(
        <pre key={key++} className="p-space-sm rounded-lg bg-surface-container-highest overflow-x-auto font-code-base text-code-base text-on-surface">
          <code>{code.join('\n')}</code>
        </pre>,
      );
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const size = level === 1 ? 'font-headline-sm' : level === 2 ? 'font-headline-sm' : 'font-body-md';
      blocks.push(
        <h4 key={key++} className={`${size} text-on-surface font-semibold`}>
          {inlineMarkdown(heading[2])}
        </h4>,
      );
      index += 1;
      continue;
    }

    // Models often use a fully bold line as a section title.
    const boldHeading = /^\*\*(.+)\*\*$/.exec(trimmed);
    if (boldHeading) {
      blocks.push(
        <h4 key={key++} className="font-body-md text-body-md text-on-surface font-semibold">
          {inlineMarkdown(boldHeading[1])}
        </h4>,
      );
      index += 1;
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ''));
        index += 1;
      }
      blocks.push(
        <ul key={key++} className="list-disc pl-5 flex flex-col gap-1 marker:text-outline">
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{inlineMarkdown(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+[.)]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length && /^\d+[.)]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+[.)]\s+/, ''));
        index += 1;
      }
      blocks.push(
        <ol key={key++} className="list-decimal pl-5 flex flex-col gap-1 marker:text-outline">
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{inlineMarkdown(item)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    if (trimmed.startsWith('> ')) {
      const quote: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith('> ')) {
        quote.push(lines[index].trim().slice(2));
        index += 1;
      }
      blocks.push(
        <blockquote key={key++} className="border-l-2 border-secondary/40 pl-space-sm text-on-surface-variant">
          {inlineMarkdown(quote.join(' '))}
        </blockquote>,
      );
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      blocks.push(<hr key={key++} className="border-outline-variant/40" />);
      index += 1;
      continue;
    }

    const paragraph = [trimmed];
    index += 1;
    while (index < lines.length && lines[index].trim() !== '' && !isBlockStart(lines[index])) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(
      <p key={key++} className="leading-relaxed">
        {inlineMarkdown(paragraph.join(' '))}
      </p>,
    );
  }

  return <div className={`flex flex-col gap-2 ${className}`}>{blocks}</div>;
}

function AgentResponse({ text }: { text: string }) {
  return <MarkdownText text={text} className="font-body-md text-body-md text-on-surface" />;
}

interface AgentSection {
  heading: string;
  body: string;
}

interface ParsedAgentResponse {
  intro: string;
  sections: AgentSection[];
}

/** Clean a line the model used as a title: bold markers, ordinals, trailing colons. */
function normalizeHeading(raw: string): string {
  return raw
    .trim()
    .replace(/^\*\*(.*)\*\*$/, '$1')
    .replace(/^__(.*)__$/, '$1')
    .replace(/\s*:\s*$/, '')
    .replace(/^\d+[.)]\s+/, '')
    .trim();
}

/**
 * Models introduce sections in a handful of ways: markdown headings, a line in
 * bold, or a short line ending in a colon before a list ("Ingredients:").
 * Recognising all three is what lets the same renderer work for any request.
 */
function readingHeading(line: string): string | null {
  const trimmed = line.trim();
  if (!trimmed) return null;

  const hash = /^#{1,4}\s+(.+)$/.exec(trimmed);
  if (hash) return normalizeHeading(hash[1]) || null;

  const bold = /^\*\*(.+)\*\*$/.exec(trimmed);
  if (bold) return normalizeHeading(bold[1]) || null;

  if (
    /^[^:]{3,90}:$/.test(trimmed) &&
    !/^[-*]\s+/.test(trimmed) &&
    !/^\d+[.)]\s+/.test(trimmed) &&
    !/^https?:\/\//.test(trimmed)
  ) {
    return normalizeHeading(trimmed) || null;
  }

  return null;
}

/** Split the answer into a lead paragraph and headed sections, without losing prose. */
function parseAgentResponse(text: string): ParsedAgentResponse {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const intro: string[] = [];
  const sections: AgentSection[] = [];
  let current: AgentSection | null = null;

  for (const line of lines) {
    const heading = readingHeading(line);
    if (heading) {
      current = { heading, body: '' };
      sections.push(current);
      continue;
    }

    if (current) {
      current.body += `${current.body ? '\n' : ''}${line}`;
    } else {
      intro.push(line);
    }
  }

  return {
    intro: intro.join('\n').trim(),
    sections: sections
      .map((section) => ({ ...section, body: section.body.trim() }))
      .filter((section) => section.heading || section.body),
  };
}

interface AgentSource {
  url: string;
  label: string;
}

function trimSourceUrl(value: string): string {
  return value.replace(/[),.;!?]+$/, '').replace(/\]$/, '');
}

function agentSourceLabel(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === '/' ? '' : parsed.pathname.replace(/\/$/, '');
    const shortPath = path.length > 28 ? `${path.slice(0, 27)}…` : path;
    return `${parsed.hostname}${shortPath}`;
  } catch {
    return url;
  }
}

/** Real sources only: URLs the tools received plus links the model wrote. */
function collectAgentSources(actions: AgentActionResponse[], text: string): AgentSource[] {
  const candidates: string[] = [];

  for (const action of actions) {
    const url = action.arguments?.url;
    if (typeof url === 'string') candidates.push(url);
  }

  for (const match of text.match(/https?:\/\/[^\s<>"'`)\]]+/g) ?? []) {
    candidates.push(match);
  }

  const seen = new Set<string>();
  const sources: AgentSource[] = [];
  for (const raw of candidates) {
    const url = trimSourceUrl(raw.trim());
    if (!/^https?:\/\//i.test(url) || seen.has(url)) continue;
    seen.add(url);
    sources.push({ url, label: agentSourceLabel(url) });
  }
  return sources;
}

function StructuredAgentResponse({
  text,
  actions = [],
}: {
  text: string;
  actions?: AgentActionResponse[];
}) {
  const { t } = useI18n();
  const parsed = useMemo(() => parseAgentResponse(text), [text]);
  const sources = useMemo(() => collectAgentSources(actions, text), [actions, text]);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <article className="bg-surface-container-low border border-outline-variant/20 rounded-xl p-space-lg flex flex-col gap-space-lg shadow-sm">
      <header className="flex flex-col gap-space-xs">
        <div className="flex items-center gap-space-xs text-primary font-label-mono-xs text-label-mono-xs">
          <span className="material-symbols-outlined text-[15px]">auto_awesome</span>
          <span className="uppercase tracking-wider font-semibold">
            {t('pages.chat.response.eyebrow')}
          </span>
        </div>
        {parsed.intro && (
          <MarkdownText
            text={parsed.intro}
            className="font-body-lg text-body-lg text-on-surface-variant [overflow-wrap:anywhere]"
          />
        )}
      </header>

      {parsed.sections.length > 0 && (
        <div
          className={`grid grid-cols-1 ${
            parsed.sections.length > 1 ? 'md:grid-cols-2' : ''
          } gap-space-md`}
        >
          {parsed.sections.map((section, index) => {
            // An odd number of cards leaves the last one alone in a two-column
            // grid. Let it span the row instead of leaving a visual hole.
            const spanFull =
              parsed.sections.length > 1 &&
              parsed.sections.length % 2 === 1 &&
              index === parsed.sections.length - 1;

            return (
              <section
                key={`${index}-${section.heading}`}
                className={`bg-surface-container rounded-lg p-space-md flex flex-col gap-space-sm min-w-0 [overflow-wrap:anywhere] ${
                  spanFull ? 'md:col-span-2' : ''
                }`}
              >
                <div className="flex items-start gap-space-sm">
                  <span className="w-7 h-7 rounded bg-surface-container-highest flex items-center justify-center text-primary font-label-mono-xs text-label-mono-xs font-medium shrink-0">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <h3 className="font-headline-sm text-headline-sm text-on-surface font-semibold pt-0.5">
                    {inlineMarkdown(section.heading)}
                  </h3>
                </div>
                {section.body && (
                  <MarkdownText
                    text={section.body}
                    className="font-body-md text-body-md text-on-surface-variant"
                  />
                )}
              </section>
            );
          })}
        </div>
      )}

      {sources.length > 0 && (
        <div className="bg-surface-container rounded-lg p-space-md flex flex-col gap-space-xs">
          <div className="flex items-center justify-between gap-space-sm">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider font-semibold">
              {t('pages.chat.response.sources')}
            </span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
              {t(
                sources.length === 1
                  ? 'pages.chat.response.sourceCountOne'
                  : 'pages.chat.response.sourceCountOther',
                { count: sources.length },
              )}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-space-xs pt-1">
            {sources.map((source) => (
              <a
                key={source.url}
                href={source.url}
                target="_blank"
                rel="noreferrer noopener"
                title={source.url}
                className="flex items-center gap-1.5 px-space-sm py-1 bg-surface-container-high hover:bg-surface-bright rounded text-on-surface font-body-sm text-body-sm transition-colors max-w-full"
              >
                <span className="material-symbols-outlined text-[14px] text-secondary">
                  verified
                </span>
                <span className="truncate">{source.label}</span>
                <span className="material-symbols-outlined text-[13px] text-outline">
                  open_in_new
                </span>
              </a>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-outline-variant/30 pt-space-sm flex flex-wrap items-center justify-between gap-space-sm">
        <span className="font-label-mono-xs text-label-mono-xs text-outline">
          {t('pages.chat.response.footer')}
        </span>
        <button
          type="button"
          onClick={() => void copy()}
          className="flex items-center gap-1.5 px-space-sm py-1 rounded bg-surface-container hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface font-label-mono-xs text-label-mono-xs transition-colors"
        >
          <span className="material-symbols-outlined text-[14px]">
            {copied ? 'check' : 'content_copy'}
          </span>
          {copied ? t('pages.chat.response.copied') : t('pages.chat.response.copy')}
        </button>
      </div>
    </article>
  );
}

function toolIcon(toolName: string): string {
  if (toolName.startsWith('web.search')) return 'travel_explore';
  if (toolName.startsWith('web.fetch')) return 'language';
  if (toolName.startsWith('memory')) return 'database';
  if (toolName.startsWith('calendar')) return 'event';
  if (toolName.startsWith('task')) return 'task_alt';
  if (toolName.startsWith('email')) return 'mail';
  return 'build';
}

function ActionPlan({
  actions,
  completed,
}: {
  actions: AgentActionResponse[];
  completed: number;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(true);
  const allDone = completed === actions.length;
  const tone = allDone ? 'text-tertiary' : 'text-secondary';

  return (
    <div className="bg-surface-container-lowest border border-outline-variant/20 rounded-xl overflow-hidden shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="w-full flex flex-wrap items-center justify-between gap-space-sm p-space-md text-left hover:bg-surface-container/40 transition-colors"
      >
        <div className="flex items-center gap-space-sm min-w-0">
          <span className={`material-symbols-outlined text-[18px] ${tone}`}>
            {allDone ? 'check_circle' : 'pending'}
          </span>
          <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider font-semibold">
            {t(actions.length === 1 ? 'pages.chat.plan.headingOne' : 'pages.chat.plan.headingOther', {
              count: actions.length,
            })}
          </span>
        </div>
        <div className="flex items-center gap-space-sm">
          <span className={`font-label-mono-xs text-label-mono-xs ${tone}`}>
            {t('pages.chat.plan.completed', { done: completed, total: actions.length })}
          </span>
          <span className="material-symbols-outlined text-[18px] text-outline">
            {open ? 'expand_less' : 'expand_more'}
          </span>
        </div>
      </button>

      {open && (
        <div className="px-space-md pb-space-md flex flex-col gap-space-xs">
          {actions.map((action, index) => (
            <div
              key={`${index}-${action.tool_name}`}
              className="bg-surface-container rounded-lg p-space-sm flex flex-wrap items-center justify-between gap-space-sm"
            >
              <div className="flex items-center gap-space-sm min-w-0">
                <span className="w-7 h-7 rounded bg-surface-container-highest flex items-center justify-center text-secondary shrink-0">
                  <span className="material-symbols-outlined text-[16px]">
                    {toolIcon(action.tool_name)}
                  </span>
                </span>
                <div className="flex flex-col min-w-0">
                  <div className="flex items-center gap-space-xs min-w-0">
                    <span className="font-code-base text-code-base text-secondary font-semibold whitespace-nowrap">
                      {action.tool_name}
                    </span>
                    <span className="font-code-base text-code-base text-outline text-[11px] truncate">
                      {summarize(action.arguments, 90)}
                    </span>
                  </div>
                  <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
                    {t(actionNarrative(action.status))}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-space-xs shrink-0">
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span
                  className={`w-5 h-5 rounded-full flex items-center justify-center ${stepBadgeTone(
                    action.status,
                  )}`}
                >
                  <span className="material-symbols-outlined text-[13px]">
                    {stepIcon(action.status)}
                  </span>
                </span>
                <span
                  className={`font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded bg-surface-container-high whitespace-nowrap ${stepTone(
                    action.status,
                  )}`}
                >
                  {action.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentMeta({ run }: { run: AgentRunResponse }) {
  const { t } = useI18n();

  return (
    <div className="flex flex-wrap items-center justify-between gap-space-sm bg-surface-container-lowest border border-outline-variant/20 rounded-xl p-space-sm shadow-sm">
      <div className="flex items-center gap-space-sm min-w-0">
        <div className="w-8 h-8 rounded bg-surface-container-high flex items-center justify-center text-secondary shrink-0">
          <span className="material-symbols-outlined text-[18px]">smart_toy</span>
        </div>
        <div className="flex flex-col min-w-0">
          <div className="flex items-center gap-space-xs min-w-0">
            <span className="font-headline-sm text-headline-sm text-on-surface font-semibold truncate">
              {t('pages.chat.run.title')}
            </span>
            <span className="font-label-mono-xs text-label-mono-xs px-space-xs py-0.5 rounded bg-primary/20 text-primary uppercase font-medium shrink-0">
              {t('pages.chat.run.badge')}
            </span>
          </div>
          <span className="font-label-mono-xs text-label-mono-xs text-outline">
            {t('pages.chat.run.id', { id: run.run_id.slice(0, 12) })}
          </span>
        </div>
      </div>
      <span
        className={`flex items-center gap-1.5 font-label-mono-xs text-label-mono-xs px-space-sm py-1 rounded bg-surface-container uppercase tracking-wider ${runTone(
          run.status,
        )}`}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-current" />
        {run.status}
      </span>
    </div>
  );
}

function riskTone(risk?: string): string {
  if (risk === 'HIGH') return 'text-error';
  if (risk === 'MEDIUM') return 'text-primary';
  return 'text-tertiary';
}

/** The pending permission request behind an ASK run, if any.
 *
 * ``run`` is part of the dependency set on purpose. Answering a question
 * continues the *same* run, and that reply can end in a permission request --
 * so with the run id alone the read would never repeat and the approval the
 * answer produced would not appear.
 */
function useRunApproval(runId: string | null, run: AgentRunResponse | null) {
  const state = useAsyncData(
    () =>
      runId
        ? permissionsApi.getPermissionRequests(runId)
        : Promise.resolve([] as PermissionRequest[]),
    [runId, run],
  );
  const pending = (state.data ?? []).find((request) => request.status === 'PENDING') ?? null;
  return { pending, loading: state.loading };
}

interface Countdown {
  expired: boolean;
  seconds: number;
}

/** Time left before the pending permission expires, or null when none is reported. */
function useCountdown(expiresAt: string | undefined): Countdown | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt]);

  if (!expiresAt) return null;
  const diff = new Date(expiresAt).getTime() - now;
  if (Number.isNaN(diff)) return null;
  return { expired: diff <= 0, seconds: Math.floor(diff / 1000) };
}

/** ``MM:SS``: a unit token rather than a sentence, so it carries no language. */
function countdownClock(seconds: number): string {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function AgentAvatar() {
  return (
    <div className="w-8 h-8 rounded bg-surface-container-highest flex items-center justify-center text-secondary flex-shrink-0 shadow-sm">
      <span className="material-symbols-outlined text-[20px]">smart_toy</span>
    </div>
  );
}

interface RunCardProps {
  turn: Turn;
  deciding: string | null;
  onDecide: (runId: string, permission: 'ALLOW' | 'DENY') => void;
  onAnswer: (runId: string, answer: string) => void;
}

function RunCard({ turn, deciding, onDecide, onAnswer }: RunCardProps) {
  const { t } = useI18n();
  const run = turn.run;
  // Hooks must run unconditionally, so the approval read is disabled by passing
  // no run id whenever the run is not actually parked on a question.
  const isWaiting = run?.status === 'WAITING_PERMISSION';
  const approval = useRunApproval(isWaiting ? (run?.run_id ?? null) : null, run ?? null);
  const busy = run ? deciding === run.run_id : false;
  // A run waiting with no permission request behind it is not asking to be
  // authorized: it is asking the user for information it is missing.
  const askedForDetail = isWaiting && !approval.loading && approval.pending === null;

  if (turn.state === 'error') {
    return (
      <div className="flex items-start gap-space-md max-w-4xl mr-auto w-full animate-rise">
        <AgentAvatar />
        <div className="flex-1 bg-error-container/20 border border-error/40 rounded-xl p-space-md flex items-start gap-space-sm">
          <span className="material-symbols-outlined text-error text-[20px]">error</span>
          <div className="flex flex-col gap-0.5">
            <span className="font-body-sm text-body-sm text-on-surface font-medium">
              {t('pages.chat.run.notCompleted')}
            </span>
            <span className="font-label-mono-xs text-label-mono-xs text-on-surface-variant">
              {turn.error}
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex items-start gap-space-md max-w-4xl mr-auto w-full animate-rise">
        <AgentAvatar />
        <div className="flex-1 bg-surface-container-low p-space-md rounded-xl flex items-center gap-space-sm">
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-typing" />
            <span
              className="w-1.5 h-1.5 rounded-full bg-secondary animate-typing"
              style={{ animationDelay: '150ms' }}
            />
            <span
              className="w-1.5 h-1.5 rounded-full bg-secondary animate-typing"
              style={{ animationDelay: '300ms' }}
            />
          </span>
          <span className="font-code-base text-code-base text-on-surface-variant">
            {t('pages.chat.run.planning')}
          </span>
        </div>
      </div>
    );
  }

  const actions = run.actions;
  const completed = actions.filter((a) => a.status === 'COMPLETED').length;
  const narrative = cleanAgentResponse(runNarrative(run, t));

  // A run that proposed no tool calls is a plain reply, so it is rendered as a
  // message: no task card and no empty plan. The plan only shows up when the
  // user actually asked for work.
  if (actions.length === 0) {
    const hasStructuredAnswer =
      run.status === 'COMPLETED' && Boolean(cleanAgentResponse(run.response));

    return (
      <div className="max-w-4xl mr-auto w-full animate-rise flex flex-col gap-space-sm">
        <AgentMeta run={run} />
        {askedForDetail ? (
          <div className="bg-surface-container-low rounded-xl p-space-md">
            <AgentResponse text={run.question ?? narrative} />
          </div>
        ) : hasStructuredAnswer ? (
          <StructuredAgentResponse text={narrative} actions={actions} />
        ) : (
          <div className="bg-surface-container-low rounded-xl p-space-md">
            <AgentResponse text={narrative} />
          </div>
        )}
        {askedForDetail && <AnswerBox run={run} busy={busy} onAnswer={onAnswer} />}
        {isWaiting && approval.pending && (
          <ApprovalCard run={run} request={approval.pending} busy={busy} onDecide={onDecide} />
        )}
      </div>
    );
  }

  return (
    <div className="max-w-4xl mr-auto w-full animate-rise flex flex-col gap-space-md">
      <AgentMeta run={run} />

      {/* The plan is evidence of what the agent did, so it comes before the answer. */}
      <ActionPlan actions={actions} completed={completed} />

      {run.status === 'COMPLETED' && cleanAgentResponse(run.response) ? (
        <StructuredAgentResponse text={narrative} actions={actions} />
      ) : (
        <div className="bg-surface-container-low rounded-xl p-space-md">
          <AgentResponse text={narrative} />
        </div>
      )}

      {/* Inline Trust Engine approval guard, or the question the run asked */}
      {askedForDetail && <AnswerBox run={run} busy={busy} onAnswer={onAnswer} />}
      {isWaiting && approval.pending && (
        <ApprovalCard run={run} request={approval.pending} busy={busy} onDecide={onDecide} />
      )}
    </div>
  );
}

interface ApprovalCardProps {
  run: AgentRunResponse;
  request: PermissionRequest | null;
  busy: boolean;
  onDecide: (runId: string, permission: 'ALLOW' | 'DENY') => void;
}

function ApprovalCard({ run, request, busy, onDecide }: ApprovalCardProps) {
  const { t } = useI18n();
  const countdown = useCountdown(request?.expires_at);

  return (
    <div className="bg-surface-container-high rounded-xl p-space-md flex flex-col gap-space-md shadow-xl">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded bg-error/20 text-error flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="material-symbols-outlined text-[22px]">gavel</span>
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="font-headline-sm text-headline-sm text-error font-semibold">
              {t('pages.chat.approval.title')}
            </span>
            <span className="font-label-mono-xs text-label-mono-xs bg-surface-container-lowest px-2 py-0.5 rounded text-secondary font-code-base whitespace-nowrap">
              {t('pages.chat.approval.policy')}
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-on-surface leading-normal">
            {run.question ?? t('pages.chat.approval.question')}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-space-sm p-space-sm bg-surface-container-low rounded">
        <div className="flex flex-col min-w-0">
          <span className="font-label-mono-xs text-label-mono-xs text-outline">
            {t('pages.chat.approval.tool')}
          </span>
          <span className="font-code-base text-code-base text-on-surface text-xs font-medium truncate">
            {request?.tool_name ?? '--'}
          </span>
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-label-mono-xs text-label-mono-xs text-outline">
            {t('pages.chat.approval.risk')}
          </span>
          <span
            className={`font-label-mono-xs text-label-mono-xs font-semibold uppercase ${riskTone(
              request?.risk_level,
            )}`}
          >
            {request?.risk_level ?? t('pages.chat.approval.notReported')}
          </span>
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-label-mono-xs text-label-mono-xs text-outline">
            {t('pages.chat.approval.skill')}
          </span>
          <span className="font-code-base text-code-base text-secondary text-xs truncate">
            {request?.skill_name ?? '--'}
          </span>
        </div>
      </div>

      {request?.reason && (
        <p className="font-body-sm text-body-sm text-on-surface-variant">{request.reason}</p>
      )}

      <div className="bg-surface-container-lowest p-space-sm rounded font-code-base text-code-base text-xs flex flex-col gap-1 overflow-x-auto text-on-surface-variant">
        <span className="text-outline uppercase text-[10px]">
          {t('pages.chat.approval.payload')}
        </span>
        <code className="text-primary-fixed whitespace-pre-wrap">
          {request ? JSON.stringify(request.arguments_summary, null, 2) : '—'}
        </code>
      </div>

      <div className="flex items-center justify-between pt-1 gap-space-sm">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-outline text-[16px]">timer</span>
          <span className="font-label-mono-xs text-label-mono-xs text-outline">
            {countdown === null
              ? t('pages.chat.approval.noExpiry')
              : countdown.expired
                ? t('pages.chat.approval.expired')
                : t('pages.chat.approval.expiresIn', {
                    time: countdownClock(countdown.seconds),
                  })}
          </span>
        </div>
        <div className="flex items-center gap-space-sm">
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide(run.run_id, 'DENY')}
            className="px-space-md py-1.5 rounded bg-surface-container text-error font-body-sm text-body-sm font-semibold hover:bg-error/20 disabled:opacity-50 transition-colors"
          >
            {t('pages.chat.approval.deny')}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => onDecide(run.run_id, 'ALLOW')}
            className="px-space-lg py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-container hover:text-on-primary-container shadow-md disabled:opacity-50 transition-all flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-[16px]">verified</span>
            {t('pages.chat.approval.allow')}
          </button>
        </div>
      </div>
    </div>
  );
}

interface AnswerBoxProps {
  run: AgentRunResponse;
  busy: boolean;
  onAnswer: (runId: string, answer: string) => void;
}

/** The reply channel for a run that stopped to ask for missing detail.
 *
 * This is not an approval: there is no permission request behind it, so the
 * only honest thing to offer is an answer. The text goes back to the same run,
 * which carries on with the detail instead of asking again.
 */
function AnswerBox({ run, busy, onAnswer }: AnswerBoxProps) {
  const { t } = useI18n();
  const [reply, setReply] = useState('');

  const submit = () => {
    const value = reply.trim();
    if (value === '' || busy) return;
    onAnswer(run.run_id, value);
    setReply('');
  };

  return (
    <div className="bg-surface-container rounded-xl p-space-md flex flex-col gap-space-sm border border-secondary/30">
      <div className="flex items-center gap-space-sm">
        <span className="material-symbols-outlined text-secondary text-[18px]">help</span>
        <span className="font-label-mono-xs text-label-mono-xs text-secondary uppercase tracking-wider">
          {t('pages.chat.answer.title')}
        </span>
      </div>
      <div className="flex items-end gap-space-sm">
        <textarea
          rows={1}
          value={reply}
          disabled={busy}
          onChange={(event) => setReply(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={t('pages.chat.answer.placeholder')}
          className="flex-1 bg-surface-container-low rounded px-space-sm py-2 font-body-sm text-body-sm text-on-surface placeholder:text-outline resize-none focus:outline-none focus:ring-1 focus:ring-secondary/40 disabled:opacity-50"
        />
        <button
          type="button"
          disabled={busy || reply.trim() === ''}
          onClick={submit}
          className="px-space-md py-2 rounded bg-secondary text-on-secondary font-body-sm text-body-sm font-semibold hover:opacity-90 disabled:opacity-50 transition-opacity flex items-center gap-1.5"
        >
          <span className="material-symbols-outlined text-[16px]">send</span>
          {t('pages.chat.answer.send')}
        </button>
      </div>
    </div>
  );
}

export default function Chat() {
  const { t, formatTime, formatRelative } = useI18n();
  const { data: overview, loading: overviewLoading } = useOverview();
  const { open: openAgents } = useAgentsDialog();
  const agentId = overview?.agent?.id ?? null;
  const model = overview?.model;
  const runtime = overview?.runtime;

  const tools = useAsyncData(() => catalogApi.listTools(), []);
  const toolItems = tools.data ?? [];

  const conversations = useAsyncData(() => conversationApi.list(), []);
  const conversationItems = conversations.data ?? [];
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; text: string } | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<string | null>(null);
  // The sidebar shows only the conversations, and the list folds away so the panel is a
  // header when the operator is not looking through history.
  const [runsOpen, setRunsOpen] = useState(true);
  // The panel itself folds away too, so the conversation can take the full
  // width; the rail that replaces it brings the runs back.
  const [sidebarOpen, setSidebarOpen] = useState(true);
  // The right inspector panel can be hidden to give more space to the chat.
  const [inspectorOpen, setInspectorOpen] = useState(false);
  // True while a conversation's runs are being read back, so an empty canvas
  // reads as "opening" rather than "no messages".
  const [loadingThread, setLoadingThread] = useState(false);
  // The conversation whose delete is in flight, so its row can disable the button.
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);

  const counter = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const createNewConversation = async () => {
    try {
      const newConv = await conversationApi.create({ title: t('pages.chat.conversation.new') });
      setCurrentConversationId(newConv.id);
      setSelectedRunId(null);
      setTurns([]);
      setNotice({ tone: 'ok', text: t('pages.chat.conversation.created') });
      // Surface it in the sidebar right away instead of waiting for the next
      // list read, so "new conversation" is visibly created.
      conversations.reload();
      return newConv.id;
    } catch (caught) {
      setNotice({ tone: 'error', text: errorText(caught, t) });
      return null;
    }
  };

  const send = async () => {
    const prompt = input.trim();
    if (prompt === '' || sending) return;
    if (!agentId) {
      setNotice({
        tone: 'error',
        text: t('pages.chat.errors.noAgent'),
      });
      return;
    }

    // Ensure we have a conversation
    let convId = currentConversationId;
    if (!convId) {
      convId = await createNewConversation();
      if (!convId) return;
    }

    const id = ++counter.current;
    setTurns((prev) => [...prev, { id, prompt, createdAt: Date.now(), state: 'running' }]);
    setInput('');
    setSending(true);
    setNotice(null);

    try {
      const run = await agentApi.createRun(agentId, prompt, convId);
      setTurns((prev) =>
        prev.map((turn) => (turn.id === id ? { ...turn, state: 'done', run } : turn)),
      );
      // The conversation's updated_at moved, so refresh the sidebar ordering.
      conversations.reload();
    } catch (caught) {
      setTurns((prev) =>
        prev.map((turn) =>
          turn.id === id ? { ...turn, state: 'error', error: errorText(caught, t) } : turn,
        ),
      );
    } finally {
      setSending(false);
    }
  };

  const decide = async (runId: string, permission: 'ALLOW' | 'DENY') => {
    setDeciding(runId);
    setNotice(null);
    try {
      const run = await agentApi.resumeRun(runId, permission);
      setTurns((prev) =>
        prev.map((turn) => (turn.run?.run_id === runId ? { ...turn, state: 'done', run } : turn)),
      );
      // A run opened from the sidebar is not in `turns`, so its read is refreshed
      // instead -- otherwise the decision would not show where it was made.
      if (needsFetch && runId === selectedRunId) fetchedRun.reload();
    } catch (caught) {
      setNotice({ tone: 'error', text: errorText(caught, t) });
    } finally {
      setDeciding(null);
    }
  };

  // A run that asked for missing detail is answered, not authorized: the reply
  // goes to the same run, which continues from the detail it lacked. Kept
  // separate from `decide` because answering can never stand in for approving.
  const answer = async (runId: string, reply: string) => {
    setDeciding(runId);
    setNotice(null);
    try {
      const run = await agentApi.answerRun(runId, reply);
      setTurns((prev) =>
        prev.map((turn) => (turn.run?.run_id === runId ? { ...turn, state: 'done', run } : turn)),
      );
      // Same as a decision: a run opened from the sidebar is not in `turns`, so
      // its read is refreshed to show the answer where it was given.
      if (needsFetch && runId === selectedRunId) fetchedRun.reload();
      conversations.reload();
    } catch (caught) {
      setNotice({ tone: 'error', text: errorText(caught, t) });
    } finally {
      setDeciding(null);
    }
  };

  const insertChip = (chip: string) => {
    setInput((prev) => (prev ? `${prev} ${chip} ` : `${chip} `));
    inputRef.current?.focus();
  };

  // The inspector follows the selected run when it lives in the conversation,
  // and otherwise falls back to a fresh read of the run id (e.g. a saved run
  // picked from the sidebar). GET returns the run's request, answer and actions,
  // so the same read also backs the thread shown in the centre column.
  const turnRuns = useMemo(
    () => turns.map((turn) => turn.run).filter((run): run is AgentRunResponse => Boolean(run)),
    [turns],
  );
  const selectedTurn = selectedRunId
    ? turns.find((turn) => turn.run?.run_id === selectedRunId) ?? null
    : null;
  const needsFetch = selectedRunId !== null && selectedTurn === null;
  const fetchedRun = useAsyncData<AgentRunResponse | null>(
    () =>
      needsFetch && selectedRunId ? agentApi.getRun(selectedRunId) : Promise.resolve(null),
    [selectedRunId],
  );
  const defaultRun = turnRuns.length > 0 ? turnRuns[turnRuns.length - 1] : null;

  const recentRuns = useMemo<RecentRun[]>(() => {
    const map = new Map<string, RecentRun>();
    turns.forEach((turn) => {
      if (turn.run) {
        map.set(turn.run.run_id, {
          runId: turn.run.run_id,
          label: turn.prompt,
          status: turn.run.status,
          updatedAt: null,
        });
      }
    });
    // Recent runs come from the backend, which lists the owner's runs in every
    // state. Fall back to the active list for an older backend that predates
    // the `recent` field.
    const backendRuns = overview?.runs.recent ?? overview?.runs.items ?? [];
    backendRuns.forEach((run) => {
      if (!map.has(run.run_id)) {
        map.set(run.run_id, {
          runId: run.run_id,
          label: run.user_request,
          status: run.status,
          updatedAt: run.updated_at,
        });
      }
    });
    return Array.from(map.values()).reverse();
  }, [turns, overview]);

  // Opening a conversation replays its runs, oldest first, so the chat shows
  // the exchange it recorded instead of an empty canvas.
  const selectConversation = async (conversationId: string) => {
    setCurrentConversationId(conversationId);
    setSelectedRunId(null);
    setTurns([]);
    setNotice(null);
    setLoadingThread(true);
    try {
      const runs = await conversationApi.listRuns(conversationId);
      setTurns(
        runs.map((run, index) => ({
          id: index + 1,
          prompt: run.user_request ?? '',
          createdAt: run.created_at ? Date.parse(run.created_at) : Date.now(),
          state: 'done' as const,
          run,
        })),
      );
      // Keep the local id counter past the replayed turns so a new message does
      // not reuse a key.
      counter.current = runs.length;
    } catch (caught) {
      setNotice({ tone: 'error', text: errorText(caught, t) });
    } finally {
      setLoadingThread(false);
    }
  };

  // Deleting a conversation removes it and its runs on the server; the sidebar
  // reloads so the list reflects it. Owner-scoped server-side, so a conversation
  // that is not the caller's is never touched.
  const deleteConversation = async (conversationId: string, title: string) => {
    if (!window.confirm(t('pages.chat.conversation.deleteConfirm', { title }))) return;
    setDeletingConversationId(conversationId);
    setNotice(null);
    try {
      await conversationApi.delete(conversationId);
      if (currentConversationId === conversationId) {
        setCurrentConversationId(null);
        setTurns([]);
      }
      conversations.reload();
      setNotice({ tone: 'ok', text: t('pages.chat.conversation.deleted') });
    } catch (caught) {
      setNotice({ tone: 'error', text: errorText(caught, t) });
    } finally {
      setDeletingConversationId(null);
    }
  };

  // Every run is a chat with its own thread: picking one from the sidebar shows
  // that exchange alone, whether it already lives in this conversation or was
  // read back by id. Its prompt and answer come from the run, its age from the
  // sidebar entry that produced it.
  const historicalEntry = selectedRunId
    ? recentRuns.find((candidate) => candidate.runId === selectedRunId) ?? null
    : null;
  // A turn already in this conversation is reused as-is; a stored run is rebuilt
  // from the read above so the canvas shows its recorded exchange.
  const isolatedTurn: Turn | null =
    selectedRunId === null
      ? null
      : (selectedTurn ??
        (fetchedRun.data
          ? {
              id: -1,
              prompt: fetchedRun.data.user_request ?? historicalEntry?.label ?? '',
              createdAt: historicalEntry?.updatedAt ? Date.parse(historicalEntry.updatedAt) : 0,
              state: 'done',
              run: fetchedRun.data,
            }
          : null));

  const selectedRun = isolatedTurn?.run ?? null;
  const inspectedRun = selectedRun ?? defaultRun;
  const inspectedActions = inspectedRun?.actions ?? [];

  // A run is open, so the canvas is that run's own thread rather than the live
  // conversation; while its read is in flight the thread is empty and the
  // progress state below stands in for it.
  const showingRun = selectedRunId !== null;
  const visibleTurns = showingRun ? (isolatedTurn ? [isolatedTurn] : []) : turns;

  // Keep the newest exchange in view as runs arrive, and the opened run in view
  // once its read lands.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, selectedRunId, fetchedRun.data]);

  return (
    <div className="flex h-[calc(100vh-3.5rem)] w-full overflow-hidden">
      {/* Left Column: Context & Sessions */}
      <aside
        className={`${
          sidebarOpen ? 'w-[280px]' : 'hidden'
        } flex-shrink-0 bg-surface-container-low flex flex-col overflow-y-auto`}
      >
        <div className="flex flex-col">
          {/* The sidebar shows conversations with a button to create a new one */}
          <div className="p-space-md flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setRunsOpen((open) => !open)}
                aria-expanded={runsOpen}
                className="flex items-center gap-1 min-w-0 text-left"
              >
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider truncate">
                  {t('pages.chat.recent.title')}
                </span>
                <span className="material-symbols-outlined text-outline text-[16px]">
                  {runsOpen ? 'expand_less' : 'expand_more'}
                </span>
              </button>
              <button
                type="button"
                aria-label={t('pages.chat.sidebar.hide')}
                title={t('pages.chat.sidebar.hide')}
                onClick={() => setSidebarOpen(false)}
                className="material-symbols-outlined text-outline text-[18px] hover:text-on-surface transition-colors flex-shrink-0"
              >
                left_panel_close
              </button>
            </div>
            {runsOpen && (
              <>
                <button
                  type="button"
                  onClick={() => void createNewConversation()}
                  className="w-full flex items-center gap-space-sm px-space-sm py-space-xs bg-primary text-on-primary rounded hover:bg-primary-container hover:text-on-primary-container transition-colors font-body-sm text-body-sm"
                >
                  <span className="material-symbols-outlined text-[16px]">add</span>
                  {t('pages.chat.conversation.new')}
                </button>
                {conversationItems.length === 0 ? (
                  <span className="font-label-mono-xs text-label-mono-xs text-outline">
                    {conversations.loading ? t('pages.chat.recent.loading') : t('pages.chat.recent.empty')}
                  </span>
                ) : (
                  conversationItems.map((conv) => (
                    <div
                      key={conv.id}
                      className={`group rounded flex items-stretch transition-colors animate-fade ${
                        currentConversationId === conv.id
                          ? 'bg-surface-container-high'
                          : 'hover:bg-surface-container'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => selectConversation(conv.id)}
                        className="flex-1 min-w-0 p-space-sm text-left flex flex-col gap-0.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-body-sm text-body-sm text-on-surface truncate">
                            {conv.title}
                          </span>
                        </div>
                        <span className="font-label-mono-xs text-label-mono-xs text-outline">
                          {formatRelative(conv.updated_at)}
                        </span>
                      </button>
                      <button
                        type="button"
                        aria-label={t('pages.chat.conversation.delete')}
                        title={t('pages.chat.conversation.delete')}
                        disabled={deletingConversationId === conv.id}
                        onClick={() => void deleteConversation(conv.id, conv.title)}
                        className="self-center mr-space-sm p-1 rounded text-outline opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 hover:text-error hover:bg-error/10 disabled:opacity-50 transition-opacity"
                      >
                        <span className="material-symbols-outlined text-[16px]">delete</span>
                      </button>
                    </div>
                  ))
                )}
              </>
            )}
          </div>
        </div>
      </aside>

      {!sidebarOpen && (
        <button
          type="button"
          aria-label={t('pages.chat.sidebar.show')}
          title={t('pages.chat.sidebar.show')}
          onClick={() => setSidebarOpen(true)}
          className="w-10 flex-shrink-0 bg-surface-container-low border-r border-outline-variant/30 flex flex-col items-center pt-space-md text-outline hover:text-on-surface transition-colors"
        >
          <span className="material-symbols-outlined text-[20px]">left_panel_open</span>
        </button>
      )}

      {/* Center Column: Conversation & Plan Canvas */}
      <main className="flex-1 flex flex-col justify-between bg-surface overflow-hidden min-w-0">
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-space-lg py-space-md flex flex-col gap-space-md"
        >
          {isolatedTurn && (
            <div className="flex items-center justify-between gap-space-md bg-surface-container-low border border-outline-variant/40 rounded-lg px-space-md py-space-sm">
              <div className="flex items-center gap-space-sm min-w-0">
                <span className="material-symbols-outlined text-secondary text-[18px]">
                  history
                </span>
                <div className="flex flex-col min-w-0">
                  <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                    {t('pages.chat.history.title')}
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant truncate">
                    {t('pages.chat.history.hint')}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedRunId(null)}
                className="px-space-md py-1.5 rounded bg-surface-container text-secondary font-body-sm text-body-sm font-semibold hover:bg-surface-container-high transition-colors whitespace-nowrap"
              >
                {t('pages.chat.history.back')}
              </button>
            </div>
          )}

          {showingRun && !isolatedTurn && (
            <div className="flex-1 flex flex-col items-center justify-center text-center gap-space-sm py-space-xl">
              <span className="material-symbols-outlined text-secondary text-[28px] animate-pulse">
                progress_activity
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                {fetchedRun.error
                  ? t('pages.chat.history.unavailable')
                  : t('pages.chat.history.loading')}
              </span>
            </div>
          )}

          {loadingThread && (
            <div className="flex-1 flex flex-col items-center justify-center text-center gap-space-sm py-space-xl">
              <span className="material-symbols-outlined text-secondary text-[28px] animate-spin">
                progress_activity
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant">
                {t('pages.chat.conversation.opening')}
              </span>
            </div>
          )}

          {turns.length === 0 && !showingRun && !loadingThread ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center gap-space-sm py-space-xl">
              <div className="w-12 h-12 rounded-xl bg-surface-container-high flex items-center justify-center text-primary">
                <span className="material-symbols-outlined text-[24px]">smart_toy</span>
              </div>
              <span className="font-headline-sm text-headline-sm text-on-surface font-semibold">
                {t('pages.chat.empty.title')}
              </span>
              <span className="font-body-sm text-body-sm text-on-surface-variant max-w-md">
                {t('pages.chat.empty.description')}
              </span>
              {!agentId && !overviewLoading && (
                <div className="flex flex-col items-center gap-2">
                  <span className="font-label-mono-xs text-label-mono-xs text-error">
                    {t('pages.chat.empty.noAgent')}
                  </span>
                  <button
                    type="button"
                    onClick={openAgents}
                    className="px-space-md py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-container hover:text-on-primary-container transition-colors flex items-center gap-1"
                  >
                    <span className="material-symbols-outlined text-[16px]">add</span>
                    {t('pages.chat.empty.createAgent')}
                  </button>
                </div>
              )}
            </div>
          ) : (
            visibleTurns.map((turn) => (
              <div key={turn.id} className="flex flex-col gap-space-md animate-rise">
                {/* User intent */}
                <div className="flex items-start gap-space-md justify-end max-w-3xl ml-auto w-full animate-fade">
                  <div className="bg-surface-container-high p-space-md rounded-xl max-w-xl min-w-0">
                    <div className="flex items-center justify-end gap-1.5 mb-1 text-on-surface-variant">
                      <span className="font-label-mono-xs text-label-mono-xs uppercase text-secondary font-medium">
                        {t('pages.chat.turn.operator')}
                      </span>
                      <span className="text-outline">·</span>
                      <span className="font-label-mono-xs text-label-mono-xs text-outline">
                        {formatTime(new Date(turn.createdAt).toISOString())}
                      </span>
                    </div>
                    <p className="font-body-md text-body-md text-on-surface leading-relaxed whitespace-pre-wrap text-left">
                      {turn.prompt}
                    </p>
                  </div>
                  <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-on-primary font-body-sm text-body-sm font-semibold flex-shrink-0">
                    {t('pages.chat.turn.initials')}
                  </div>
                </div>

                {/* Agent run result */}
                <RunCard turn={turn} deciding={deciding} onDecide={decide} onAnswer={answer} />
              </div>
            ))
          )}
        </div>

        {notice && (
          <div
            className={`mx-space-md mb-space-xs rounded p-space-sm flex items-center gap-space-xs font-body-sm text-body-sm ${
              notice.tone === 'ok'
                ? 'bg-tertiary/10 text-tertiary'
                : 'bg-error-container/30 text-error'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">
              {notice.tone === 'ok' ? 'check_circle' : 'error'}
            </span>
            <span>{notice.text}</span>
          </div>
        )}

        {/* Input bar */}
        <footer className="p-space-md bg-surface-container-low flex flex-col gap-space-xs">
          <div className="flex items-center gap-space-xs overflow-x-auto pb-1">
            <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase mr-1">
              {t('pages.chat.input.shortcuts')}
            </span>
            {QUICK_CHIPS.map((chip) => (
              <button
                key={chip}
                type="button"
                onClick={() => insertChip(t(chip))}
                className="px-2 py-0.5 rounded bg-surface-container font-label-mono-xs text-label-mono-xs text-secondary hover:bg-surface-container-high transition-colors whitespace-nowrap"
              >
                {t(chip)}
              </button>
            ))}
          </div>

          <div className="bg-surface-container rounded-lg p-space-sm flex flex-col gap-space-xs">
            <textarea
              ref={inputRef}
              rows={2}
              value={input}
              disabled={sending}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  void send();
                }
              }}
              placeholder={t('pages.chat.input.placeholder')}
              className="bg-transparent text-on-surface font-body-md text-body-md placeholder:text-outline resize-none focus:outline-none w-full"
            />
            <div className="flex items-center justify-between pt-1 gap-space-sm">
              <div className="flex items-center gap-space-xs">
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-container-high text-on-surface font-label-mono-xs text-label-mono-xs">
                  <span className="material-symbols-outlined text-secondary text-[14px]">
                    psychology
                  </span>
                  <span className="truncate max-w-[160px]">
                    {model?.model ?? t('pages.chat.input.modelFallback')}
                  </span>
                </div>
                <div className="flex items-center gap-1 px-2 py-1 rounded bg-surface-container-high text-tertiary font-label-mono-xs text-label-mono-xs">
                  <span className="material-symbols-outlined text-[14px]">construction</span>
                  <span>{t('pages.chat.input.toolCount', { count: toolItems.length })}</span>
                </div>
              </div>
              <div className="flex items-center gap-space-sm">
                <span className="font-label-mono-xs text-label-mono-xs text-outline hidden md:inline">
                  {t('pages.chat.input.hint')}
                </span>
                <button
                  type="button"
                  disabled={sending || input.trim() === ''}
                  onClick={() => void send()}
                  className="px-space-md py-1.5 rounded bg-primary text-on-primary font-body-sm text-body-sm font-semibold hover:bg-primary-container hover:text-on-primary-container disabled:opacity-50 transition-all flex items-center gap-1"
                >
                  <span>{sending ? t('pages.chat.input.sending') : t('pages.chat.input.send')}</span>
                  <span className="material-symbols-outlined text-[16px]">send</span>
                </button>
              </div>
            </div>
          </div>
        </footer>
      </main>

      {!inspectorOpen && (
        <button
          type="button"
          aria-label={t('pages.chat.inspector.show')}
          title={t('pages.chat.inspector.show')}
          onClick={() => setInspectorOpen(true)}
          className="w-10 flex-shrink-0 bg-surface-container-low border-l border-outline-variant/30 flex flex-col items-center pt-space-md text-outline hover:text-on-surface transition-colors"
        >
          <span className="material-symbols-outlined text-[20px]">right_panel_open</span>
        </button>
      )}

      {/* Right Column: STDOUT & Live Telemetry Inspector */}
      {inspectorOpen && (
        <aside className="w-[320px] flex-shrink-0 bg-surface-container-lowest flex flex-col justify-between overflow-y-auto">
          <div className="flex flex-col">
            <div className="p-space-md bg-surface-container-low flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-secondary text-[18px]">terminal</span>
                <span className="font-headline-sm text-headline-sm text-on-surface font-semibold text-sm">
                  {t('pages.chat.inspector.title')}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`font-label-mono-xs text-label-mono-xs px-1.5 py-0.5 rounded ${
                    sending ? 'text-secondary bg-secondary/10' : 'text-outline bg-surface-container'
                  }`}
                >
                  {sending ? t('pages.chat.badges.streaming') : t('pages.chat.badges.idle')}
                </span>
                <button
                  type="button"
                  aria-label={t('pages.chat.inspector.hide')}
                  title={t('pages.chat.inspector.hide')}
                  onClick={() => setInspectorOpen(false)}
                  className="material-symbols-outlined text-outline text-[18px] hover:text-on-surface transition-colors"
                >
                  right_panel_close
                </button>
              </div>
            </div>

            <div className="p-space-sm bg-surface-container-low grid grid-cols-2 gap-space-xs">
              <div className="bg-surface-container p-2 rounded flex flex-col">
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {t('common.actions')}
                </span>
                <span className="font-label-mono-sm text-label-mono-sm text-tertiary font-bold">
                  {inspectedActions.length}
                </span>
              </div>
              <div className="bg-surface-container p-2 rounded flex flex-col">
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {t('common.status')}
                </span>
                <span
                  className={`font-label-mono-sm text-label-mono-sm font-bold ${
                    inspectedRun ? runTone(inspectedRun.status) : 'text-outline'
                  }`}
                >
                  {inspectedRun?.status ?? t('pages.chat.badges.idle')}
                </span>
              </div>
            </div>

            <div className="p-space-md flex flex-col gap-2">
              <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                {t('pages.chat.inspector.affinity')}
              </span>
              <div className="w-full bg-surface-container-low p-space-sm rounded">
                <span className="font-label-mono-xs text-label-mono-xs text-outline leading-5 block">
                  {t('pages.chat.inspector.affinityNote')}
                </span>
              </div>
            </div>

            <div className="px-space-md flex flex-col gap-1 pb-space-md">
              <div className="flex items-center justify-between mb-1">
                <span className="font-label-mono-xs text-label-mono-xs text-outline uppercase tracking-wider">
                  {t('pages.chat.inspector.timedLogs')}
                </span>
                <span className="font-label-mono-xs text-label-mono-xs text-outline">
                  {overview?.system.environment ?? '--'}
                </span>
              </div>
              {inspectedActions.length === 0 ? (
                <div className="font-code-base text-code-base text-[11px] text-outline bg-surface-container-low p-space-sm rounded">
                  {t('pages.chat.inspector.noActions')}
                </div>
              ) : (
                <div className="font-code-base text-code-base text-[11px] leading-relaxed flex flex-col gap-2 text-on-surface-variant bg-surface-container-low p-space-sm rounded">
                  {inspectedActions.map((action, index) => (
                    <div key={`${index}-${action.tool_name}`}>
                      <span className="text-primary">{t('pages.chat.inspector.call')}</span>{' '}
                      {action.tool_name} →{' '}
                      <span className={stepTone(action.status)}>{action.status}</span>
                      <div className="text-on-surface-variant/80 pl-2">
                        <code>{summarize(action.arguments, 140)}</code>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="p-space-md bg-surface-container-low flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <span className="font-label-mono-xs text-label-mono-xs text-outline">
                {t('pages.chat.runtime.label', { provider: runtime?.provider ?? '--' })}
              </span>
              <span
                className={`font-label-mono-xs text-label-mono-xs ${
                  runtime?.available ? 'text-secondary' : 'text-error'
                }`}
              >
                {runtime?.available
                  ? t('pages.chat.runtime.available')
                  : t('pages.chat.runtime.unavailable')}
              </span>
            </div>
            <div className="flex items-center justify-between text-on-surface font-label-mono-xs text-label-mono-xs pt-1">
              <span className="truncate">
                {runtime?.detail || t('pages.chat.runtime.noDetail')}
              </span>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}
