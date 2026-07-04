import type { AgentMessage, AgentMessageRole, Artifact, AgentToolCallState, AgentDisplayMessage } from '../types/agent';

function parseToolPayloadJson(raw: string): unknown | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    // Continue: content may be wrapped in a fenced json block.
  }
  if (!trimmed.startsWith('```')) return null;
  const lines = trimmed.split('\n');
  if (!lines[0].trim().startsWith('```')) return null;
  const body: string[] = [];
  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i].trim().startsWith('```')) break;
    body.push(lines[i]);
  }
  const candidate = body.join('\n').trim();
  if (!candidate) return null;
  try {
    return JSON.parse(candidate);
  } catch {
    return null;
  }
}

function leakedToolName(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const obj = payload as Record<string, unknown>;

  if (Array.isArray(obj.tool_calls) && obj.tool_calls.length > 0) {
    const first = obj.tool_calls[0] as Record<string, unknown>;
    const fn = first?.function as Record<string, unknown> | undefined;
    if (typeof fn?.name === 'string') return fn.name;
    if (typeof first?.name === 'string') return first.name;
  }

  if (obj.function && typeof obj.function === 'object') {
    const fn = obj.function as Record<string, unknown>;
    if (typeof fn.name === 'string') return fn.name;
  }

  if ('arguments' in obj) {
    if (typeof obj.name === 'string') return obj.name;
    if (typeof obj.tool === 'string') return obj.tool;
  }

  return null;
}

export function sanitizeAssistantDisplayText(text: string): string {
  const payload = parseToolPayloadJson(text);
  if (!payload) return text;
  const toolName = leakedToolName(payload);
  if (!toolName) return text;

  const normalized = toolName.toLowerCase();
  if (normalized.includes('todo_write') || normalized.includes('todo')) {
    return 'I updated the todo list and will continue with the next steps.';
  }
  return `I used the ${toolName} tool and I will continue with the next step.`;
}

/** Convert a persisted display message (with reconstructed tool chips) into the
 * frontend AgentMessage, attaching `thinking` from the tool calls. */
export function displayToAgentMessage(m: AgentDisplayMessage): AgentMessage {
  const role: AgentMessageRole = m.role === 'assistant' ? 'agent' : 'user';
  const thinking =
    role === 'agent' && m.tools && m.tools.length > 0
      ? {
          toolCalls: m.tools.map((t, i) => ({
            toolCallId: `db-${m.id}-${i}`,
            toolName: t.name,
            argsSummary: t.summary,
            status: 'success',
          })),
          durationSeconds: m.duration_seconds ?? 0,
        }
      : undefined;
  return {
    id: m.id,
    thread_id: m.session_id,
    agent_id: '',
    role,
    text: role === 'agent' ? sanitizeAssistantDisplayText(m.text) : m.text,
    images: m.images,
    artifacts: [],
    created_at: m.created_at,
    thinking,
  };
}

// ── Public: AgentMessage construction ───────────────────────────────────

/** Build an AgentMessage for thread storage. */
export function buildAgentMessage(
  id: string,
  text: string,
  role: AgentMessageRole,
  threadId: string,
  agentId: string,
  artifacts?: Artifact[],
  thinking?: AgentMessage['thinking'],
  images?: string[],
): AgentMessage {
  return {
    id,
    thread_id: threadId,
    agent_id: agentId,
    role,
    text,
    images,
    artifacts: artifacts ?? [],
    created_at: new Date().toISOString(),
    thinking,
  };
}

// ── Public: Thinking metadata assembly ──────────────────────────────────

/** Assemble thinking metadata from parsed markers or live store fallback. */
export function buildThinkingMeta(
  parsedSteps: string[],
  parsedDuration: number,
  fallbackToolCalls?: AgentToolCallState[],
  fallbackStartedAt?: number | null,
): AgentMessage['thinking'] | undefined {
  if (parsedSteps.length > 0) {
    return {
      toolCalls: parsedSteps.map((step, i) => ({
        toolCallId: `parsed-${i}`,
        toolName: step,
        argsSummary: '',
        status: 'success',
      })),
      durationSeconds: parsedDuration,
    };
  }
  if (fallbackToolCalls && fallbackToolCalls.length > 0) {
    return {
      toolCalls: fallbackToolCalls,
      durationSeconds: fallbackStartedAt
        ? Math.round((Date.now() - fallbackStartedAt) / 1000)
        : 0,
    };
  }
  return undefined;
}

// ── Public: Thinking marker parsing ─────────────────────────────────────

/**
 * Parse `<!-- thinking duration=N -->...<!-- /thinking -->` markers from
 * agent message content. Returns the cleaned text and extracted metadata.
 */
export function parseThinkingMarkers(content: string): {
  cleanText: string;
  thinkingSteps: string[];
  durationSeconds: number;
} {
  if (!content) {
    return { cleanText: '', thinkingSteps: [], durationSeconds: 0 };
  }
  const pattern = /<!-- thinking duration=(\d+) -->\n([\s\S]*?)<!-- \/thinking -->\n*/g;
  const allSteps: string[] = [];
  let totalDuration = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(content)) !== null) {
    totalDuration += parseInt(match[1], 10);
    const block = match[2].trim();
    if (block) allSteps.push(...block.split('\n').filter(Boolean));
  }
  if (allSteps.length === 0 && totalDuration === 0) {
    return { cleanText: content, thinkingSteps: [], durationSeconds: 0 };
  }
  const cleanText = content.replace(pattern, '').trim();
  return { cleanText, thinkingSteps: allSteps, durationSeconds: totalDuration };
}
