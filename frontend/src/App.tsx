import { useMemo, useState } from 'react';
import { A2UIRenderer } from './a2ui';
import { streamAgUi } from './agui';
import type { A2UIComponent, A2UIOperation, AgEvent, ChatMessage } from './types';

const CLASSIC_16 = [
  'RUN_STARTED', 'RUN_FINISHED', 'RUN_ERROR', 'STEP_STARTED', 'STEP_FINISHED',
  'TEXT_MESSAGE_START', 'TEXT_MESSAGE_CONTENT', 'TEXT_MESSAGE_END',
  'TOOL_CALL_START', 'TOOL_CALL_ARGS', 'TOOL_CALL_END', 'TOOL_CALL_RESULT',
  'STATE_SNAPSHOT', 'STATE_DELTA', 'MESSAGES_SNAPSHOT', 'CUSTOM',
];

const EXAMPLE = `Rough week schedule:\nMonday: class 9:00-10:15 and 1:00-2:15; free after 3:00 PM.\nTuesday: class 10:30-11:45; work 4:00-8:00 PM.\nWednesday: same as Monday.\nThursday: same as Tuesday.\nFriday: class 9:00-10:15; free after 11:00 AM.\nSaturday: mostly free after noon.\nSunday: free 1:00-6:00 PM.\nI prefer not to study after 10 PM.\n\nAssignments:\nPhysics reading — due Tuesday 9:00 AM — 30 minutes\nPhysics homework — due Thursday 11:59 PM — 2 hours\nNew Testament reading — due Friday 9:00 AM — 30 minutes\nAlgorithms problem set — due Sunday 11:59 PM — 3 hours\nMobile app feature — due Monday 8:00 AM — 4 hours`;

export function App() {
  const [input, setInput] = useState(EXAMPLE);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<AgEvent[]>([]);
  const [components, setComponents] = useState<Record<string, A2UIComponent>>({});
  const [busy, setBusy] = useState(false);

  const seen = useMemo(() => new Set(events.map((e) => e.type)), [events]);

  function consume(event: AgEvent) {
    setEvents((prev) => [...prev, event]);

    if (event.type === 'TEXT_MESSAGE_START') {
      setChat((prev) => [...prev, { role: 'assistant', content: '' }]);
    }
    if (event.type === 'TEXT_MESSAGE_CONTENT') {
      const delta = String(event.delta ?? '');
      setChat((prev) => {
        const copy = [...prev];
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].role === 'assistant') {
            copy[i] = { ...copy[i], content: copy[i].content + delta };
            break;
          }
        }
        return copy;
      });
    }

    if (event.type === 'CUSTOM' && event.name === 'a2ui') {
      const op = event.value as A2UIOperation;
      if (op.updateComponents?.components) {
        setComponents((prev) => {
          const next = { ...prev };
          for (const component of op.updateComponents!.components) next[component.id] = component;
          return next;
        });
      }
    }
  }

  async function buildSchedule() {
    if (!input.trim() || busy) return;
    setBusy(true);
    setEvents([]);
    setComponents({});
    setChat([{ role: 'user', content: input }]);
    try {
      await streamAgUi('/agent', [{ id: crypto.randomUUID(), role: 'user', content: input }], consume);
    } catch (error) {
      consume({ type: 'CLIENT_ERROR', message: String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function demoEvents() {
    if (busy) return;
    setBusy(true);
    setEvents([]);
    try {
      const demoMessage = [{ id: crypto.randomUUID(), role: 'user' as const, content: 'Demonstrate the classic event catalogue.' }];
      await streamAgUi('/demo-events?terminal=finished', demoMessage, consume);
      await streamAgUi('/demo-events?terminal=error', demoMessage, consume);
    } catch (error) {
      consume({ type: 'CLIENT_ERROR', message: String(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AG-UI 1.0 transport · A2UI declarative schedule</p>
          <h1>Study Planner Agent</h1>
        </div>
        <button className="secondary" onClick={demoEvents} disabled={busy}>Demonstrate classic 16</button>
      </header>

      <section className="workspace">
        <div className="left-stack">
          <section className="panel composer">
            <div className="panel-title">
              <h2>Student input</h2>
              <span>rough schedule + assignments + due dates + estimates</span>
            </div>
            <textarea value={input} onChange={(e) => setInput(e.target.value)} />
            <button onClick={buildSchedule} disabled={busy}>{busy ? 'Streaming…' : 'Build week schedule'}</button>
          </section>

          <section className="panel chat-panel">
            <div className="panel-title"><h2>Chat</h2><span>TEXT_MESSAGE_* renders here</span></div>
            <div className="chat-log">
              {chat.length === 0 ? <div className="empty-state">Send the example or replace it with your own week.</div> : null}
              {chat.map((message, i) => (
                <div className={`bubble ${message.role}`} key={i}>
                  <small>{message.role}</small>
                  <p>{message.content}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="panel schedule-panel">
            <div className="panel-title"><h2>A2UI surface</h2><span>custom catalog renderer</span></div>
            <A2UIRenderer components={components} />
          </section>
        </div>

        <aside className="panel event-panel">
          <div className="panel-title sticky">
            <div>
              <h2>AG-UI event stream</h2>
              <span>{events.length} received · {CLASSIC_16.filter((type) => seen.has(type)).length}/16 classic types seen</span>
            </div>
            <button className="ghost" onClick={() => setEvents([])}>Clear</button>
          </div>

          <div className="event-catalogue">
            {CLASSIC_16.map((type) => <span key={type} className={seen.has(type) ? 'seen' : ''}>{type}</span>)}
          </div>
          <p className="catalogue-note">This panel intentionally tracks the classic 16 requested for the demo. Current AG-UI also defines newer event families.</p>

          <div className="event-list">
            {events.map((event, i) => (
              <details className="event-card" key={`${i}-${event.type}`} open={i === events.length - 1}>
                <summary><b>{String(i + 1).padStart(3, '0')}</b><span>{event.type}</span></summary>
                <pre>{JSON.stringify(event, null, 2)}</pre>
              </details>
            ))}
          </div>
        </aside>
      </section>
    </main>
  );
}
