import type { FormEvent } from "react";
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import type { SecretRequirement } from "../../../shared/api/backendTypes";

export type SecretFormValues = Record<string, Record<string, string>>;

export interface SecretPromptModalProps {
  requirements: SecretRequirement[];
  values: SecretFormValues;
  submitting: boolean;
  onChange: (secretRef: string, fieldName: string, value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

export function SecretPromptModal({
  requirements,
  values,
  submitting,
  onChange,
  onSubmit,
  onCancel,
}: SecretPromptModalProps) {
  const [visibleSecrets, setVisibleSecrets] = useState<Set<string>>(new Set());

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  function isSecretVisible(secretRef: string, fieldName: string): boolean {
    return visibleSecrets.has(`${secretRef}:${fieldName}`);
  }

  function toggleSecretVisibility(secretRef: string, fieldName: string) {
    setVisibleSecrets((current) => {
      const key = `${secretRef}:${fieldName}`;
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-xl rounded-2xl bg-white p-5 shadow-2xl"
      >
        <div className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Секреты
        </div>
        <h2 className="mt-1 text-lg font-semibold text-slate-950">
          Требуются учётные данные
        </h2>

        <div className="mt-5 max-h-[52vh] space-y-5 overflow-y-auto pr-1">
          {requirements.map((requirement) => (
            <section key={requirement.secret_ref}>
              <div className="text-sm font-semibold text-slate-900">
                {requirement.title}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {requirement.secret_ref}
              </div>

              <div className="mt-3 space-y-3">
                {requirement.fields
                  .filter((field) => field.secret)
                  .map((field) => (
                    <label key={field.name} className="block">
                      <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                        {field.title ?? field.name}
                      </span>
                      <div className="mt-1 flex rounded-xl border border-slate-200 bg-white focus-within:border-slate-400">
                        <input
                          type={isSecretVisible(requirement.secret_ref, field.name) ? "text" : "password"}
                          required={field.required}
                          value={values[requirement.secret_ref]?.[field.name] ?? ""}
                          onChange={(event) =>
                            onChange(requirement.secret_ref, field.name, event.target.value)
                          }
                          className="min-w-0 flex-1 rounded-xl bg-transparent px-3 py-2 text-sm text-slate-700 outline-none"
                        />
                        <button
                          type="button"
                          aria-label={
                            isSecretVisible(requirement.secret_ref, field.name)
                              ? "Скрыть секрет"
                              : "Показать секрет"
                          }
                          title={
                            isSecretVisible(requirement.secret_ref, field.name)
                              ? "Скрыть секрет"
                              : "Показать секрет"
                          }
                          onClick={() => toggleSecretVisibility(requirement.secret_ref, field.name)}
                          className="grid w-10 place-items-center rounded-xl text-slate-400 hover:bg-slate-50 hover:text-slate-700"
                        >
                          {isSecretVisible(requirement.secret_ref, field.name) ? (
                            <EyeOff size={16} />
                          ) : (
                            <Eye size={16} />
                          )}
                        </button>
                      </div>
                    </label>
                  ))}
              </div>
            </section>
          ))}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-2xl bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Сохранение..." : "Сохранить и запустить"}
          </button>
        </div>
      </form>
    </div>
  );
}
