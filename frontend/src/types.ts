export interface ActionableDeeplink {
  deeplink: string;
  description: string;
  message?: string | null;
  originalType?: string | null;
}

export interface ValidationDeeplink {
  deeplink: string;
  key: string;
  resultType?: string | null;
  condition?: string | null;
  value?: string | null;
}

export interface StepGroup {
  steps: string[];
  actionableDeeplink?: ActionableDeeplink | null;
  validationDeeplink?: ValidationDeeplink | null;
}

export type Category = "auto" | "manual" | "critical";

export interface Action {
  actionName: string;
  description: string;
  stepGroups: StepGroup[];
  category: Category;
}

export interface Goal {
  goal: string;
  title: string;
  score: number;
  actions: Action[];
}

export interface Meta {
  latency_ms: number;
  cache_hit: boolean;
  model: string;
  cost_usd: number;
  fallback?: string;
}

export interface TroubleshootResponse {
  query: string;
  query_variations: string[];
  response: { contexts: Goal[] };
  meta: Meta;
}
