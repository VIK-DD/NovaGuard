import catalog from "./commands.json";

// Host-only commands are not published at all — see core/command_visibility.py
// for the list and the reasoning. Leaving "owner" out of this union is what
// makes TypeScript object if one is ever added back to the catalog by mistake.
export type CommandAudience = "everyone" | "server-admin";

export interface CommandCategory {
  emoji: string;
  name: string;
  blurb: string;
  audience: CommandAudience;
  note?: string;
  commands: string[];
}

export const commandCategories = catalog as CommandCategory[];

export const commandCount = commandCategories.reduce(
  (total, category) => total + category.commands.length,
  0,
);
