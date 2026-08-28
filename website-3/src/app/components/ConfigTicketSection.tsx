import type {
  GuildChannel,
  GuildConfig,
  GuildRole,
  GuildSettings,
} from "../../lib/api/schemas";
import { isModuleActive } from "../moduleCatalog";
import ChannelSelect from "./ChannelSelect";
import { Section } from "./ConfigPrimitives";
import RoleSelect from "./RoleSelect";

interface TicketSectionProps {
  guildId: string;
  settings: GuildSettings;
  tickets: GuildConfig["tickets"];
  channels: GuildChannel[];
  roles: GuildRole[];
  fieldErrors: Record<string, string>;
  dirty: boolean;
  publishPending: boolean;
  publishError: boolean;
  notice: string | null;
  onChannelChange: (value: string | null) => void;
  onRoleChange: (value: string | null) => void;
  onPublish: () => void;
}

export function TicketSection(props: TicketSectionProps) {
  return (
    <Section
      id="tickets"
      icon="clipboard-text"
      kicker="Tickets"
      description="Choose which role can claim and manage member support tickets."
      active={isModuleActive(props.settings, "tickets")}
    >
      <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <ChannelSelect
          label="Ticket panel channel"
          value={props.settings.ticket_panel_channel}
          channels={props.channels}
          error={props.fieldErrors.ticket_panel_channel}
          onChange={props.onChannelChange}
        />
        <RoleSelect
          label="Ticket staff role"
          value={props.settings.ticket_staff_role}
          roles={props.roles.filter(
            (role) => role.manages_threads || role.id === props.settings.ticket_staff_role,
          )}
          error={props.fieldErrors.ticket_staff_role}
          onChange={props.onRoleChange}
        />
      </div>
      <p className="mt-2 text-xs leading-5 text-ink-muted">
        Only roles with <strong>Manage Threads</strong> are offered. The selected role also needs
        <strong> View Channel</strong> in the panel channel.
      </p>
      <div className="mt-6 rounded-lg border border-line bg-bg-subtle p-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium">
              {props.tickets.panel_message_id ? "Panel is live" : "Panel not published"}
            </p>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              {props.dirty
                ? "Save these settings before publishing the panel."
                : props.tickets.ready
                  ? "Publishing again updates the existing message instead of creating a duplicate."
                  : "Choose both fields above, save, then publish."}
            </p>
          </div>
          <button
            type="button"
            disabled={
              props.dirty ||
              !props.settings.ticket_panel_channel ||
              !props.settings.ticket_staff_role ||
              props.publishPending
            }
            onClick={props.onPublish}
            className="ng-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {props.publishPending
              ? "Publishing…"
              : props.tickets.panel_message_id
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

      <div className="mt-6 border-t border-line pt-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">Open tickets</p>
          <span className="rounded-full border border-line bg-bg-subtle px-2.5 py-1 text-xs text-ink-muted">
            {props.tickets.open_count}
          </span>
        </div>
        {props.tickets.open.length > 0 ? (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {props.tickets.open.map((ticket) => (
              <li key={ticket.thread_id} className="flex items-center justify-between gap-3 py-3">
                <span className="min-w-0">
                  <span className="block truncate text-sm text-ink">{ticket.opener_name}</span>
                  <span className="mt-0.5 block text-xs text-ink-faint">
                    Opened {new Date(ticket.created_at).toLocaleString("en-US")}
                  </span>
                </span>
                <a
                  href={`https://discord.com/channels/${props.guildId}/${ticket.thread_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="ng-touch-target inline-flex shrink-0 items-center rounded-md px-2 text-sm text-primary hover:underline"
                >
                  Open in Discord ↗
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-ink-muted">No tracked tickets are open.</p>
        )}
      </div>
    </Section>
  );
}
