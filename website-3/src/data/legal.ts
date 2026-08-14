export const LEGAL_EFFECTIVE_DATE = "August 12, 2026";

/** First year of publication. The closing year is derived at build time. */
export const LEGAL_COPYRIGHT_START_YEAR = 2019;

export const LEGAL_OPERATOR = {
  name: "Breabin Victor",
  contactAddress: "support@novaguard.fun",
  privacyEmail: "support@novaguard.fun",
  country: "Republic of Moldova",
} as const;

export const LEGAL_INFRASTRUCTURE = {
  hostingProvider: "Oracle Cloud Infrastructure",
  hostingRegion: "Germany",
  backupProvider: "Google Drive",
  backupLocation: "Google's global infrastructure",
} as const;

export const MOLDOVA_AUTHORITY = {
  name: "National Center for Personal Data Protection of the Republic of Moldova (CNPDCP)",
  href: "https://datepersonale.md/about/contacts/",
  email: "centru@datepersonale.md",
} as const;
