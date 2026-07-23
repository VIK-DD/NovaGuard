// Landing feature list. `tag` is a representative slash command shown as a
// right-aligned reference, not decoration.
export interface Feature {
  title: string;
  body: string;
  tag: string;
}

export const features: Feature[] = [
  {
    title: "Moderation",
    body: "Purge, kick, ban, timeout and warnings — slash-native, logged, and centralized where your staff can see them.",
    tag: "/warn add",
  },
  {
    title: "A setup that respects you",
    body: "Real select menus and channel pickers, every channel optional. Per-server settings live in SQLite, not a pile of env vars.",
    tag: "/setup",
  },
  {
    title: "Tickets & giveaways",
    body: "Private-thread tickets, button-entry giveaways and self-role panels that survive every restart.",
    tag: "/ticketpanel",
  },
  {
    title: "Levels & economy",
    body: "Automatic XP with level-up celebrations, plus a full server economy — daily, work, shop, and a little gambling.",
    tag: "/rank",
  },
  {
    title: "GitHub-aware",
    body: "Commits, releases and repository watch delivered straight to the channels you choose.",
    tag: "/ghwatch",
  },
  {
    title: "Claude, in chat",
    body: "Ask a question and get an answer right inside Discord, powered by Claude.",
    tag: "/ask",
  },
];
