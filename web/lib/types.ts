export type Status = "new" | "confirmed" | "false_positive" | "reported" | "blocked";

export interface FindingRow {
  id: string;
  source: string;
  entity_type: string | null;
  url: string;
  host: string | null;
  handle: string | null;
  title: string | null;
  text: string | null;
  status: Status;
  operator: string | null;
  brands: string[];
  matched_keywords: string[];
  ai_score: number | null;
  category: string | null;
  category_suggested: boolean;
  tags: string[];
  needs_review: boolean;
  is_live: boolean | null;
  is_impersonation: boolean;
  first_seen: string;
  last_seen: string;
  views: number | null;
  followers: number | null;
  subscribers: number | null;
  likes: number | null;
  screenshot: number | null;
}

export interface FindingDetail extends FindingRow {
  landing_url: string | null;
  landing_raw: string | null;
  advertiser: string | null;
  media_urls: string[];
  suggested_action: string | null;
  original_status: string | null;
  complaint_status: string | null;
  review_reasons: string[];
  ai_label: string | null;
  ai_reason: string | null;
  published_at: string | null;
  enrichment: Record<string, any>;
  enriched_at: string | null;
  raw: Record<string, any>;
  evidence: { id: number; kind: string; url: string | null; sha256: string; bytes: number; captured_at: string }[];
  links: {
    type: string;
    value: string;
    direction: "in" | "out";
    finding: { id: string; source: string; url: string; status: Status } | null;
  }[];
  events: { at: string; kind: string; actor: string | null; data: Record<string, any> }[];
}

export interface Overview {
  range: { from: string; to: string };
  total: number;
  new: number;
  imported: number;
  by_source: Record<string, number>;
  by_status: Record<string, number>;
  daily: { day: string; count: number }[];
  top_operators: { operator: string; count: number }[];
  needs_review: number;
  impersonation: number;
  collectors: { collector: string; status: string; started_at: string; items_found: number; errors: number; duration_ms: number | null }[];
}
