export type AgEvent = {
  type: string;
  [key: string]: unknown;
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};
