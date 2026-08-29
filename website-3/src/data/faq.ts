export type FaqLink = {
  href: string;
  label: string;
};

export type FaqItem = {
  question: string;
  answer: string;
  links?: FaqLink[];
};

export type FaqSection = {
  id: string;
  label: string;
  intro: string;
  items: FaqItem[];
};

export const FAQ_SECTIONS: FaqSection[] = [
  {
    id: "getting-started",
    label: "Getting started",
    intro: "The essentials before NovaGuard joins your server.",
    items: [
      {
        question: "What is NovaGuard?",
        answer:
          "NovaGuard is a Discord moderation and utility bot for communities that want one clear place for setup, safety, roles, tickets, levels, giveaways, voice tools and everyday server utilities.",
        links: [
          { href: "/commands", label: "Explore the commands" },
          { href: "/setup", label: "Read the setup guide" },
        ],
      },
      {
        question: "Is NovaGuard free to use?",
        answer:
          "Yes. The current NovaGuard release is free to use, with no paid tier, advertising or behavioral tracking. If that model ever changes, the website and terms will be updated before the change applies.",
      },
      {
        question: "How do I add and configure the bot?",
        answer:
          "Add NovaGuard through the official invite, then run /setup in Discord. Every setup channel is optional, and the dashboard gives administrators a visual way to review and change the same server configuration.",
        links: [{ href: "/setup", label: "Start with the four-step guide" }],
      },
      {
        question: "Why has a new slash command not appeared yet?",
        answer:
          "NovaGuard syncs commands globally with Discord. Discord can take up to about one hour to show a new or changed command in every server, so a short delay after an update is normal.",
      },
      {
        question: "Does NovaGuard need Administrator permission?",
        answer:
          "No. NovaGuard requests the specific permissions its features use, never the blanket Administrator permission. Discord role hierarchy still applies, so the NovaGuard role must sit above every role or member it needs to manage.",
      },
    ],
  },
  {
    id: "features-control",
    label: "Features & control",
    intro: "Use the whole toolkit or keep the footprint small.",
    items: [
      {
        question: "Can I enable only the features my community needs?",
        answer:
          "Yes. Setup channels and optional modules can be configured independently. NovaGuard keeps working when only part of the setup is complete, and you can change the configuration later without reinstalling the bot.",
      },
      {
        question: "What can NovaGuard manage?",
        answer:
          "Its public command groups cover moderation, AutoMod, logs, tickets, role panels, welcome and goodbye flows, levels, economy, giveaways, voice activity, reminders, GitHub updates, privacy controls and general utilities. Host-only maintenance commands are deliberately not advertised as public commands.",
        links: [{ href: "/commands", label: "See the complete command directory" }],
      },
      {
        question: "What does the dashboard do?",
        answer:
          "The dashboard uses Discord OAuth to show only servers you are allowed to manage. From there you can review settings and configure supported features without memorising every setup command. OAuth tokens and sessions are protected by the NovaGuard API and can be ended by logging out.",
      },
      {
        question: "Why can NovaGuard not manage a role or member?",
        answer:
          "The usual cause is Discord hierarchy: a bot cannot act on a role or member positioned above its own highest role. Move the NovaGuard role higher, confirm the specific permission is enabled, then try the action again.",
      },
      {
        question: "Can I vote for NovaGuard on Top.gg?",
        answer:
          "The Top.gg listing is currently waiting for verification. The vote page shows the current state and will point to the official listing once approval is complete.",
        links: [{ href: "/vote", label: "Check the Top.gg status" }],
      },
    ],
  },
  {
    id: "privacy-data",
    label: "Privacy & data",
    intro: "What is processed, why it is needed and what you can control.",
    items: [
      {
        question: "What personal data does NovaGuard process?",
        answer:
          "Depending on enabled features, NovaGuard may process Discord user, server, role and channel IDs; server configuration; moderation and feature records; limited OAuth profile data; and security audit information. The Privacy Policy contains the purpose and retention period for each category.",
        links: [{ href: "/privacy", label: "Read the data inventory" }],
      },
      {
        question: "Does NovaGuard store every message?",
        answer:
          "No. AutoMod and meaningful-message XP may inspect messages in real time, but NovaGuard does not build its own archive of ordinary message history. If a server enables Server Logs, edited or deleted excerpts may be reposted to that server's chosen private Discord log channel.",
      },
      {
        question: "Does the AI feature read the whole server?",
        answer:
          "No. When /ask is enabled and a member runs it, only the question submitted with that command is sent to Anthropic to generate the answer. NovaGuard does not store a local history of those questions, and members should not include sensitive information in prompts.",
      },
      {
        question: "Does NovaGuard sell data or use advertising trackers?",
        answer:
          "No. NovaGuard does not sell personal data, serve advertising or use behavioral advertising trackers. Essential cookies are used only where needed for the password gate, security and Discord dashboard sessions.",
      },
      {
        question: "How can I export or delete my data?",
        answer:
          "Run /privacy export to receive the records tied to your Discord ID. Run /privacy delete to receive a final export and erase or anonymise your live records. Server owners also have server-level export and deletion controls.",
        links: [{ href: "/privacy", label: "Review all privacy controls" }],
      },
      {
        question: "What happens to server data if NovaGuard is removed?",
        answer:
          "Server data enters a 30-day recovery window so an accidental removal can be reversed. If NovaGuard is not added back, the data is erased after that window. A server owner who wants immediate erasure can use /privacy server-delete; the deletion ledger prevents a later backup restore from bringing erased references back.",
        links: [{ href: "/server-admin-notice", label: "Open the administrator notice" }],
      },
    ],
  },
  {
    id: "reliability-support",
    label: "Reliability & support",
    intro: "Where to look when something feels off.",
    items: [
      {
        question: "How can I check whether NovaGuard is online?",
        answer:
          "Use the public status page. It reports the bot, database and maintenance state from NovaGuard's readiness API, with a short edge fallback so a temporary network interruption does not create a misleading blank page.",
        links: [{ href: "/status", label: "Open service status" }],
      },
      {
        question: "Are backups protected?",
        answer:
          "NovaGuard creates encrypted backups, verifies archive and SQLite integrity, keeps an off-site copy and performs restore checks. Decrypted restore-test files are removed after verification, and the deletion ledger is applied before recovered data can return to service.",
      },
      {
        question: "Where should I ask for help or report a bug?",
        answer:
          "Join the NovaGuard Discord community for setup help and ordinary bug reports. Include what you were trying to do, the command or page involved and the exact error, but never post bot tokens, OAuth secrets, backup keys or personal exports.",
        links: [
          { href: "https://discord.gg/CbDy3GyhWm", label: "Join the support server" },
        ],
      },
      {
        question: "How should I report a security or privacy issue?",
        answer:
          "Report sensitive security or privacy matters privately using the contact route in the Privacy Policy. Do not publish exploit details, personal data or credentials in a public channel while the issue is being investigated.",
        links: [{ href: "/privacy", label: "Find the private contact details" }],
      },
    ],
  },
];

export const FAQ_ITEM_COUNT = FAQ_SECTIONS.reduce(
  (total, section) => total + section.items.length,
  0,
);
