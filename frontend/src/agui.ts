import type { AgEvent } from './types';

const API = 'http://localhost:8000';
export async function streamAgUi(
  path: string,
  messages: Array<{
    id: string;
    role: 'user' | 'assistant';
    content: string;
  }>,
  onEvent: (event: AgEvent) => void,
): Promise<void> {
  const body = {
    threadId: crypto.randomUUID(),
    runId: crypto.randomUUID(),
    state: {},
    messages,
    tools: [],
    context: [],
    forwardedProps: {},
  };

  const response = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();

    throw new Error(
      `AG-UI endpoint failed: ${response.status} ${errorText}`,
    );
  }

  if (!response.body) {
    throw new Error('AG-UI endpoint returned no response body.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, {
      stream: true,
    });

    /*
     * SSE allows:
     *
     * \n\n
     * \r\n\r\n
     * \r\r
     *
     * Normalize everything to \n before parsing.
     */
    buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

    let boundary = buffer.indexOf('\n\n');

    while (boundary !== -1) {
      const packet = buffer.slice(0, boundary);

      buffer = buffer.slice(boundary + 2);

      parsePacket(packet, onEvent);

      boundary = buffer.indexOf('\n\n');
    }
  }

  // Flush any remaining bytes from TextDecoder.
  buffer += decoder.decode();

  buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  if (buffer.trim()) {
    parsePacket(buffer, onEvent);
  }
}

function parsePacket(
  packet: string,
  onEvent: (event: AgEvent) => void,
) {
  const lines = packet.split('\n');

  const dataLines = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());

  if (dataLines.length === 0) {
    return;
  }

  const raw = dataLines.join('\n');

  try {
    const parsed = JSON.parse(raw) as AgEvent;

    console.log('[AG-UI EVENT]', parsed);

    onEvent(parsed);
  } catch (error) {
    console.error(
      '[AG-UI PARSE ERROR]',
      error,
      raw,
    );

    onEvent({
      type: 'CLIENT_PARSE_ERROR',
      raw,
      error: String(error),
    });
  }
}