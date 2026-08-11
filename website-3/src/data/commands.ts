import catalog from "./commands.json";

export type CommandAudience = "everyone" | "server-admin" | "owner";

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
