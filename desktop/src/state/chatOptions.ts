// Per-conversation chat settings: model/provider/effort plus the extended-thinking
// and capability toggles. New chats inherit the workspace defaults; changing any
// setting while a conversation is open records an override for that conversation
// only, so each thread keeps its own model + effort (contract §8).

export interface ChatOptions {
  provider: string;
  model: string;
  effort: string;
  thinking: boolean;
  webSearch: boolean;
  research: boolean;
  // Let the agent actually run code (code_execution tool) in this chat — every run is
  // still gated by the Approve prompt. The Code tab forces this on regardless.
  codeExec: boolean;
}

export const DEFAULT_CHAT_OPTIONS: ChatOptions = {
  provider: "zhipu",
  model: "glm-4-plus",
  effort: "High",
  thinking: false,
  webSearch: false,
  research: false,
  codeExec: false,
};

// Merge a conversation's override onto the workspace defaults.
export function effectiveOptions(
  base: ChatOptions,
  override?: Partial<ChatOptions>,
): ChatOptions {
  return override ? { ...base, ...override } : base;
}
