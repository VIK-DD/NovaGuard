// Command catalog — mirrors SETUP.md §5. Update both together.
export interface CommandCategory {
  emoji: string;
  name: string;
  blurb: string;
  commands: string[];
}

export const commandCategories: CommandCategory[] = [
  {
    emoji: "🚀",
    name: "Setup",
    blurb: "One-command setup dashboard with buttons, select menus and a channel picker.",
    commands: ["/setup", "/config view|export|backup|reset"],
  },
  {
    emoji: "⚙️",
    name: "System",
    blurb: "Health, status and the automatic update pipeline.",
    commands: ["/ping", "/uptime", "/status", "/botinfo", "/doctor", "/help", "/latest", "/updates", "/forceupdate"],
  },
  {
    emoji: "🐙",
    name: "Developer",
    blurb: "GitHub intelligence delivered into your server.",
    commands: ["/github", "/repo", "/dev", "/health", "/commits", "/release", "/ghwatch"],
  },
  {
    emoji: "🧰",
    name: "Utility",
    blurb: "Everyday tools for members and staff.",
    commands: ["/userinfo", "/serverinfo", "/avatar", "/roleinfo", "/poll", "/remind", "/reminders", "/timestamp", "/choose", "/color"],
  },
  {
    emoji: "🎉",
    name: "Fun",
    blurb: "Quick games and icebreakers.",
    commands: ["/8ball", "/coinflip", "/dice", "/rps", "/trivia", "/joke", "/ship", "/vibecheck"],
  },
  {
    emoji: "🛡️",
    name: "Moderation",
    blurb: "Slash-native moderation with warnings kept on record.",
    commands: ["/purge", "/kick", "/ban", "/timeout", "/untimeout", "/slowmode", "/announce", "/warn add|list|clear"],
  },
  {
    emoji: "🏆",
    name: "Levels",
    blurb: "Automatic XP for chatting, with level-up celebrations.",
    commands: ["/rank", "/leaderboard"],
  },
  {
    emoji: "👋",
    name: "Welcome",
    blurb: "Join/leave embeds and auto-role for newcomers.",
    commands: ["/welcome set", "/welcome off", "/welcome test"],
  },
  {
    emoji: "📋",
    name: "Logs",
    blurb: "Deleted/edited messages, joins, leaves, bans and mod actions.",
    commands: ["/logs set", "/logs off"],
  },
  {
    emoji: "🎭",
    name: "Roles",
    blurb: "Button panels where members pick their own roles — persistent across restarts.",
    commands: ["/rolepanel"],
  },
  {
    emoji: "🎁",
    name: "Giveaways",
    blurb: "Button entry, live counter, automatic winner draw.",
    commands: ["/giveaway start|end|reroll"],
  },
  {
    emoji: "🎫",
    name: "Tickets",
    blurb: "One button opens a private thread with the staff role pinged.",
    commands: ["/ticketpanel"],
  },
  {
    emoji: "🤖",
    name: "AutoMod",
    blurb: "Invite blocking, anti-spam and a managed bad-word list.",
    commands: ["/automod status|invites|spam", "/automod badword add|remove|list"],
  },
  {
    emoji: "💰",
    name: "Economy",
    blurb: "A full server economy — daily rewards, work, gambling and a shop.",
    commands: ["/balance", "/daily", "/work", "/pay", "/gamble", "/slots", "/richest", "/shop", "/buy"],
  },
  {
    emoji: "🧠",
    name: "AI",
    blurb: "Claude answers right in the chat (needs an Anthropic API key).",
    commands: ["/ask"],
  },
];
