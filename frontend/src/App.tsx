import { useState } from 'react';
import { streamAgUi } from './agui';
import type { AgEvent, ChatMessage } from './types';

const CLASSIC_16 = [
  'RUN_STARTED', 'RUN_FINISHED', 'RUN_ERROR', 'STEP_STARTED', 'STEP_FINISHED',
  'TEXT_MESSAGE_START', 'TEXT_MESSAGE_CONTENT', 'TEXT_MESSAGE_END',
  'TOOL_CALL_START', 'TOOL_CALL_ARGS', 'TOOL_CALL_END', 'TOOL_CALL_RESULT',
  'STATE_SNAPSHOT', 'STATE_DELTA', 'MESSAGES_SNAPSHOT', 'CUSTOM',
];

const EXAMPLE = `Rough week schedule:
Monday: class 9:00-10:15 and 1:00-2:15; free after 3:00 PM.
Tuesday: class 10:30-11:45; work 4:00-8:00 PM.
Wednesday: same as Monday.
Thursday: same as Tuesday.
Friday: class 9:00-10:15; free after 11:00 AM.
Saturday: mostly free after noon.
Sunday: free 1:00-6:00 PM.
I prefer not to study after 10 PM.

Assignments:
Physics reading — due Tuesday 9:00 AM — 30 minutes
Physics homework — due Thursday 11:59 PM — 2 hours
New Testament reading — due Friday 9:00 AM — 30 minutes
Algorithms problem set — due Sunday 11:59 PM — 3 hours
Mobile app feature — due Monday 8:00 AM — 4 hours`;

function valueAsText(value: unknown): string {
  if (value === undefined || value === null) return 'unknown';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

type EventEntry = {
  event: AgEvent;
  description: string;
};

export function App() {
  // State used by the input, chat, and event inspector.
  const [input, setInput] = useState(EXAMPLE);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<EventEntry[]>([]);
  const [busy, setBusy] = useState(false);

  const seen = new Set(events.map(({ event }) => event.type));
  const classicTypesSeen = CLASSIC_16.filter((type) => seen.has(type)).length;

  // Every AG-UI event appears in the inspector; text events also update chat.
  function consume(event: AgEvent) {
    let description: string;

    switch (event.type) {
      case 'RUN_STARTED':
        description = `Agent started run ${valueAsText(event.runId)} in conversation ${valueAsText(event.threadId)}.`;
        break;
      case 'RUN_FINISHED':
        description = `Agent completed run ${valueAsText(event.runId)}.`;
        break;
      case 'RUN_ERROR':
        description = `Agent error (${valueAsText(event.code ?? 'Error')}): ${valueAsText(event.message)}`;
        break;
      case 'STEP_STARTED':
        description = `Started task: ${valueAsText(event.stepName)}.`;
        break;
      case 'STEP_FINISHED':
        description = `Finished task: ${valueAsText(event.stepName)}.`;
        break;
      case 'TEXT_MESSAGE_START':
        setChat((prev) => [...prev, { role: 'assistant', content: '' }]);
        description = `Started a ${valueAsText(event.role)} message (${valueAsText(event.messageId)}).`;
        break;
      case 'TEXT_MESSAGE_CONTENT':
        setChat((messages) => {
                    // missing code challenge #3 
          

          return updated;
        });
        description = `Received text fragment: “${valueAsText(event.delta)}”`;
        break;
      case 'TEXT_MESSAGE_END':
        description = `Message ${valueAsText(event.messageId)} is complete.`;
        break;
      case 'TOOL_CALL_START':
        description = `Calling tool ${valueAsText(event.toolCallName)} (${valueAsText(event.toolCallId)}).`;
        break;
      case 'TOOL_CALL_ARGS':
        description = `Received argument fragment for ${valueAsText(event.toolCallId)}: ${valueAsText(event.delta)}`;
        break;
      case 'TOOL_CALL_END':
        description = `Arguments complete for ${valueAsText(event.toolCallId)}. The tool may still be running.`;
        break;
      case 'TOOL_CALL_RESULT':
        description = `Tool ${valueAsText(event.toolCallId)} returned: ${valueAsText(event.content)}`;
        break;
      case 'STATE_SNAPSHOT':
        description = `Received complete agent state: ${valueAsText(event.snapshot)}`;
        break;
      case 'STATE_DELTA': {
        const changes = Array.isArray(event.delta) ? event.delta : [];
        const summary = changes.map((change: unknown) => {
          if (!change || typeof change !== 'object') return valueAsText(change);
          const patch = change as Record<string, unknown>;
          return `${valueAsText(patch.op)} ${valueAsText(patch.path)}` +
            ('value' in patch ? ` → ${valueAsText(patch.value)}` : '') +
            ('from' in patch ? ` from ${valueAsText(patch.from)}` : '');
        }).join('; ');
        description = `Agent state changes: ${summary || valueAsText(event.delta)}`;
        break;
      }
      case 'MESSAGES_SNAPSHOT':
        description = `Received conversation history: ${Array.isArray(event.messages) ? event.messages.length : 'unknown number of'} messages.`;
        break;
      case 'CUSTOM':
        description = `Custom event ${valueAsText(event.name)}: ${valueAsText(event.value)}`;
        break;
      case 'CLIENT_PARSE_ERROR':
        description = `Could not parse an incoming event: ${valueAsText(event.error)}`;
        break;
      case 'CLIENT_ERROR':
        description = `Request or stream failed: ${valueAsText(event.message)}`;
        break;
      default:
        description = `Received event: ${event.type}. Inspect its payload below.`;
        break;
    }

    // Keep the original payload alongside the explanation produced by its case.
    setEvents((prev) => [...prev, { event, description }]);
  }

  // Shared request lifecycle for building a schedule and demonstrating events.
  async function runStream(
    path: string,
    message = input,
    resetChat = false,
    resetEvents = true,
  ) {
    setBusy(true);

    if (resetEvents) setEvents([]);
    if (resetChat) {
      setChat([{ role: 'user', content: message }]);
    }

    try {
      await streamAgUi(
        path,
        [{ id: crypto.randomUUID(), role: 'user', content: message }],
        consume,
      );
    } catch (error) {
      consume({ type: 'CLIENT_ERROR', message: String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function buildSchedule() {
    if (!input.trim() || busy) return;
    await runStream('/agent', input, true);
  }

  async function demoEvents() {
    if (busy) return;

    const message = 'Demonstrate the classic event catalogue.';
    // Keep both runs in the inspector to show both terminal event types.
    await runStream('/demo-events?terminal=finished', message);
    await runStream('/demo-events?terminal=error', message, false, false);
  }

  // Page layout: student input and chat on the left, event inspector on the right.
  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AG-UI 1.0 transport · Text study planner</p>
          <h1>Study Planner Agent</h1>
        </div>
        <button className="secondary" onClick={demoEvents} disabled={busy}>
          Demonstrate classic 16
        </button>
      </header>

      <section className="workspace">
        <div className="left-stack">
          <section className="panel composer">
            <div className="panel-title">
              <h2>Student input</h2>
              <span>rough schedule + assignments + due dates + estimates</span>
            </div>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
            />
            <button onClick={buildSchedule} disabled={busy}>
              {busy ? 'Streaming…' : 'Build week schedule'}
            </button>
          </section>

          <section className="panel chat-panel">
            <div className="panel-title">
              <h2>Chat</h2>
              <span>TEXT_MESSAGE_* renders here</span>
            </div>
            <div className="chat-log">
              {chat.length === 0 && (
                <div className="empty-state">
                  Send the example or replace it with your own week.
                </div>
              )}
              {chat.map((message, index) => (
                <div className={`bubble ${message.role}`} key={index}>
                  <small>{message.role}</small>
                  <p>{message.content}</p>
                </div>
              ))}
            </div>
          </section>
        </div>

        <aside className="panel event-panel">
          <div className="panel-title sticky">
            <div>
              <h2>AG-UI event stream</h2>
              <span>
                {events.length} received · {classicTypesSeen}/16 classic types seen
              </span>
            </div>
            <button className="ghost" onClick={() => setEvents([])}>
              Clear
            </button>
          </div>

          <div className="event-catalogue">
            {CLASSIC_16.map((type) => (
              <span key={type} className={seen.has(type) ? 'seen' : ''}>
                {type}
              </span>
            ))}
          </div>
          <p className="catalogue-note">
            This panel intentionally tracks the classic 16 requested for the demo. Current AG-UI also defines newer event families.
          </p>

          <div className="event-list">
            {events.map(({ event, description }, index) => (
              <details
                className="event-card"
                key={`${index}-${event.type}`}
                open={index === events.length - 1}
              >
                <summary>
                  <b>{String(index + 1).padStart(3, '0')}</b>
                  <span>{event.type}</span>
                </summary>
                <pre>{description}{'\n\n'}{JSON.stringify(event, null, 2)}</pre>
              </details>
            ))}
          </div>
        </aside>
      </section>
    </main>
  );
}
