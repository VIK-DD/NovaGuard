import type {
  GuildChannel,
  GuildConfig,
  GuildRole,
  GuildSettings,
} from "../../lib/api/schemas";
import { isModuleActive } from "../moduleCatalog";
import ChannelSelect from "./ChannelSelect";
import { Section } from "./ConfigPrimitives";
import IgnoreListEditor from "./IgnoreListEditor";

type RolePanel = GuildConfig["role_panels"][number];

interface RolePanelsSectionProps {
  guildId: string;
  settings: GuildSettings;
  panels: GuildConfig["role_panels"];
  channels: GuildChannel[];
  roles: GuildRole[];
  fieldErrors: Record<string, string>;
  dirty: boolean;
  title: string;
  description: string;
  roleIds: string[];
  editingId: string | null;
  notice: string | null;
  publishPending: boolean;
  publishError: boolean;
  onChannelChange: (value: string | null) => void;
  onTitleChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onRoleIdsChange: (value: string[]) => void;
  onCancelEdit: () => void;
  onEdit: (panel: RolePanel) => void;
  onPublish: () => void;
}

export function RolePanelsSection(props: RolePanelsSectionProps) {
  return (
    <Section
      id="roles"
      icon="users-three"
      kicker="Role panels"
      description="Let members add and remove safe, self-service roles without staff intervention."
      active={isModuleActive(props.settings, "roles")}
    >
      <div className="max-w-md border-t border-line pt-6">
        <ChannelSelect
          label="Default panel channel"
          value={props.settings.role_panel_channel}
          channels={props.channels}
          error={props.fieldErrors.role_panel_channel}
          onChange={props.onChannelChange}
        />
        <p className="mt-2 text-xs leading-5 text-ink-muted">
          Save a new default channel before publishing a new panel. Existing panels stay in their
          original channel when edited.
        </p>
      </div>

      <div className="mt-7 rounded-lg border border-line bg-bg-subtle p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-sm font-medium">
              {props.editingId ? "Edit role panel" : "Create role panel"}
            </p>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              One panel can offer up to five roles that NovaGuard is allowed to assign.
            </p>
          </div>
          {props.editingId && (
            <button
              type="button"
              onClick={props.onCancelEdit}
              className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-ink"
            >
              Cancel editing
            </button>
          )}
        </div>

        <div className="mt-5 grid gap-5">
          <label className="block">
            <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">Panel title</span>
            <input
              aria-label="Panel title"
              value={props.title}
              maxLength={80}
              onChange={(event) => props.onTitleChange(event.target.value)}
              placeholder="Community roles"
              className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
            />
            <span className="mt-1 block text-right text-xs text-ink-faint">
              {props.title.length}/80
            </span>
          </label>

          <label className="block">
            <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">Description</span>
            <textarea
              aria-label="Description"
              value={props.description}
              maxLength={1000}
              rows={4}
              onChange={(event) => props.onDescriptionChange(event.target.value)}
              placeholder="Choose the roles that match what you want to follow."
              className="mt-1.5 w-full resize-y rounded-md border border-line bg-card px-3 py-2 text-sm leading-6 outline-none focus:border-ink"
            />
            <span className="mt-1 block text-right text-xs text-ink-faint">
              {props.description.length}/1000
            </span>
          </label>

          <IgnoreListEditor
            label="Self-assignable roles"
            prefix="@"
            value={props.roleIds}
            options={props.roles.filter(
              (role) => role.assignable || props.roleIds.includes(role.id),
            )}
            maxItems={5}
            onChange={props.onRoleIdsChange}
          />
        </div>

        <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-5 text-ink-muted">
            {props.dirty
              ? "Save the channel change before publishing."
              : props.editingId
                ? "The tracked Discord message will be updated in place."
                : "Publishing creates one persistent Discord message."}
          </p>
          <button
            type="button"
            disabled={
              props.dirty ||
              (!props.editingId && !props.settings.role_panel_channel) ||
              !props.title.trim() ||
              !props.description.trim() ||
              props.roleIds.length === 0 ||
              props.publishPending
            }
            onClick={props.onPublish}
            className="ng-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {props.publishPending
              ? "Publishing…"
              : props.editingId
                ? "Update panel"
                : "Publish panel"}
          </button>
        </div>

        {props.notice && (
          <p
            role={props.publishError ? "alert" : "status"}
            className={`mt-3 border-t border-line pt-3 text-sm ${
              props.publishError ? "text-primary" : "text-good"
            }`}
          >
            {props.notice}
          </p>
        )}
      </div>

      <div className="mt-7 border-t border-line pt-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">Tracked panels</p>
          <span className="rounded-full border border-line bg-bg-subtle px-2.5 py-1 text-xs text-ink-muted">
            {props.panels.length}
          </span>
        </div>
        {props.panels.length > 0 ? (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {props.panels.map((panel) => {
              const channel = props.channels.find((item) => item.id === panel.channel_id);
              return (
                <li
                  key={panel.message_id}
                  className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-ink">{panel.title}</span>
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      #{channel?.name ?? "deleted-channel"} · {panel.role_ids.length} roles · updated{" "}
                      {new Date(panel.updated_at).toLocaleString("en-US")}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => props.onEdit(panel)}
                      className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-ink"
                    >
                      Edit
                    </button>
                    <a
                      href={`https://discord.com/channels/${props.guildId}/${panel.channel_id}/${panel.message_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-primary hover:underline"
                    >
                      Open ↗
                    </a>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-ink-muted">No role panels are tracked yet.</p>
        )}
      </div>
    </Section>
  );
}
