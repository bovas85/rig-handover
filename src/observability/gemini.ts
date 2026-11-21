import { GoogleGenAI } from '@google/genai';
import { wrapGemini } from 'langsmith/wrappers/gemini';

export interface TracedGeminiOptions {
  apiKey?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
  tracingEnabled?: boolean;
}

/**
 * Returns an instance of GoogleGenAI wrapped with LangSmith tracing
 * if LANGSMITH_TRACING=true or tracingEnabled is explicitly passed.
 */
export function getTracedGemini(options: TracedGeminiOptions = {}): GoogleGenAI {
  const apiKey = options.apiKey || process.env.GEMINI_API_KEY || '';
  const rawClient = new GoogleGenAI({ apiKey });

  const isTracing =
    options.tracingEnabled !== undefined
      ? options.tracingEnabled
      : process.env.LANGSMITH_TRACING === 'true' || process.env.LANGSMITH_TRACING === '1';

  if (!isTracing) {
    return rawClient;
  }

  return wrapGemini(rawClient, {
    project_name: process.env.LANGSMITH_PROJECT || 'agent-seat',
    tags: options.tags || ['agent-telemetry'],
    metadata: {
      service: 'rig',
      ...options.metadata,
    },
  });
}
