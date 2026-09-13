export const SUPPORTED_EXTENSIONS = [
  ".txt",
  ".md",
  ".csv",
  ".json",
  ".xlsx",
  ".xls",
  ".pdf",
  ".docx",
] as const;

export const THRESHOLDS = {
  near_quote_relative_diff: 0.005,
  low_dispersion_cv: 0.01,
  outlier_relative_diff: 0.1,
  line_item_match_relative_diff: 0.005,
  text_similarity: 0.92,
  structure_similarity: 0.8,
  min_common_line_items: 3,
  min_text_chars: 80,
  arithmetic_step_cv: 0.05,
  geometric_ratio_cv: 0.02,
  discount_rate_band: 0.001,
  line_item_jaccard: 0.9,
  min_line_item_set_common: 8,
  shared_block_size: 200,
  min_shared_blocks: 3,
  shared_block_coverage: 0.1,
  near_quote_secondary_relative_diff: 0.02,
} as const;

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MAX_PDF_FILE_BYTES = 40 * 1024 * 1024;
export const MAX_TEXT_FOR_COMPARE = 120_000;
export const MAX_PDF_PAGES = 200;
export const MAX_PDF_TEXT_CHARS = 1_000_000;
export const MAX_INPUT_FILES = 80;
export const MAX_JSON_DEPTH = 100;
export const MAX_JSON_NODES = 100_000;

export type SignalLevel = "高" | "中" | "低";
export type ParseStatus = "OK" | "PARTIAL" | "ERROR" | "UNSUPPORTED";
export type QuoteKind = "control" | "explicit_total" | "untaxed_total" | "generic_total";

export type Quote = {
  label: string;
  value: number;
  source: string;
  locator: string;
  raw: string;
  kind: QuoteKind;
  extraction_method?: "text" | "ocr";
};

export type LineItem = {
  name: string;
  name_key: string;
  unit: string | null;
  specification: string | null;
  feature: string | null;
  comparison_key: string | null;
  comparability_status: "COMPARABLE" | "INSUFFICIENT_DATA";
  comparability_missing: string[];
  amount: number;
  source: string;
  locator: string;
  raw: string;
};

export type FilePublic = {
  path: string;
  extension: string;
  size_bytes: number;
  sha256: string;
  normalized_sha256?: string;
  parse_status: ParseStatus;
  text_chars?: number;
  quote_count?: number;
  line_item_count?: number;
  parse_warnings?: { locator: string; reason: string; raw: string }[];
};

export type ParsedFile = {
  public: FilePublic;
  text: string;
  quotes: Quote[];
  items: LineItem[];
  metadata: Record<string, { key: string; value: string }[]>;
  error?: string;
};

export type Bidder = {
  name: string;
  files: FilePublic[];
  quotes: Quote[];
  primary_quote: Quote | null;
  line_items: LineItem[];
  line_item_count: number;
  comparable_line_item_count: number;
  insufficient_line_item_count: number;
  metadata: Record<string, { key: string; value: string }[]>;
  _internal_files: { public: FilePublic; text: string }[];
};

export type Signal = {
  id?: string;
  code: string;
  rule_id?: string;
  kind: string;
  level: SignalLevel;
  title: string;
  scope: string;
  description: string;
  legal_basis: string;
  evidence: unknown[];
  manual_action: string;
  auto_conclusion: false;
};

export type RelationClue = {
  bidder_a: string;
  bidder_b: string;
  relation: string;
  source: string;
  row?: number;
  raw?: Record<string, string>;
};

export type ReviewResult = {
  product: string;
  review_type: string;
  project: string;
  generated_at: string;
  config: {
    supported_extensions: string[];
    thresholds: typeof THRESHOLDS;
    enabled_rule_ids: string[];
  };
  legal_notice: { conclusion: string; scope: string };
  bidders: Omit<Bidder, "_internal_files">[];
  signals: Signal[];
  relation_clues: RelationClue[];
  unsupported_files: FilePublic[];
  parse_errors: { path: string; bidder: string; error: string }[];
  parse_warnings: { path: string; bidder: string; locator: string; error: string; raw: string }[];
  summary: {
    bidder_count: number;
    file_count: number;
    parsed_file_count: number;
    partial_file_count: number;
    quote_count: number;
    signal_count: number;
    high_signal_count: number;
    unsupported_file_count: number;
    parse_error_count: number;
  };
  auto_conclusion: false;
  manual_review_required: true;
};
