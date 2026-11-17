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
  updateDataModel?: {
    surfaceId: string;
    path?: string;
    value: unknown;
  };
  deleteSurface?: {
    surfaceId: string;
  };
};

export type A2UIComponent = {
  id: string;
  component: string;
  children?: string[];
  [key: string]: unknown;
};

/** A live surface: its components plus the data model the form fields are bound to. */
export type A2UISurface = {
  surfaceId: string;
  catalogId: string;
  components: Record<string, A2UIComponent>;
  data: Record<string, unknown>;
};

/** What a Button sends back to the agent. */
export type A2UIAction = {
  name: string;
  surfaceId: string;
  data: Record<string, unknown>;
};

export type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
};