import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage, type JsonObject, type Run } from "../api";
import { parseJsonObject } from "../lib/json";
import { JsonField } from "./JsonField";
import { Button, ErrorNote, FormActions, Modal } from "./ui";

/** Starts a run of an action or operator, then opens the run's page. */
export function RunDialog({
  title,
  start,
  onClose,
}: {
  title: string;
  start: (input: JsonObject) => Promise<Run>;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [text, setText] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = parseJsonObject(text);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!parsed.ok) return;
    setBusy(true);
    setError(null);
    try {
      const run = await start(parsed.value);
      navigate(`/runs/${run.id}`);
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <JsonField
          id="run-input"
          label="Input"
          value={text}
          onChange={setText}
          help={
            <>
              Optional JSON object, available to templates as{" "}
              <code className="font-mono">{"{{ input.<key> }}"}</code>.
            </>
          }
        />
        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!parsed.ok}>
            Run now
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}
