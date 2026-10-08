export type AgEvent = {
  type: string;
  [key: string]: unknown;
};

export type A2UIOperation = {
  version: string;
  createSurface?: {
    surfaceId: string;
    catalogId: string;
  };
  updateComponents?: {
    surfaceId: string;
    components: A2UIComponent[];
  };
};

export type A2UIComponent = {
  id: string;
  component: string;
  children?: string[];
  [key: string]: unknown;
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};
