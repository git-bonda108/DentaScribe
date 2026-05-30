"""Design tokens — single source of truth for colors, spacing, typography."""

COLORS = {
    # Primary palette (dental-clean)
    "primary": "#0EA5A4",          # teal — main actions
    "primary_dark": "#067A79",     # hover / pressed
    "primary_light": "#D6F4F3",    # tinted background

    # Accents
    "mint": "#6FE4D6",
    "navy": "#0B2A4A",             # headings / depth
    "amber": "#F59E0B",             # warnings
    "red": "#DC2626",               # critical / unconfirmed
    "green": "#16A34A",             # success / validated

    # Neutrals
    "bg": "#F7FBFC",
    "surface": "#FFFFFF",
    "border": "#E2E8F0",
    "muted": "#64748B",
    "text": "#1E2327",              # matches Dentsi theme-color
    "text_subtle": "#475569",
}

SPACING = {"xs": "4px", "sm": "8px", "md": "16px", "lg": "24px", "xl": "32px"}

RADIUS = {"sm": "6px", "md": "10px", "lg": "14px", "pill": "999px"}
