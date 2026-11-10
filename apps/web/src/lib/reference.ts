/**
 * Cached reference data: units, categories, brands.
 *
 * These rarely change but were fetched again on every visit to Products and
 * Inventory. Each list is kept for a few minutes per shop, concurrent callers
 * share one request, a failed request is not cached, and anything that edits
 * the lists (the taxonomy dialog) forces a fresh copy. Live data (stock,
 * movements, dashboard figures) is deliberately NOT cached here.
 */

import { apiRequest } from "@/lib/api";
import type { Brand, Category, UnitOfMeasure } from "@/lib/types";

const TTL_MS = 5 * 60_000;

type Entry = { at: number; promise: Promise<unknown> };
const cache = new Map<string, Entry>();

function cached<T>(key: string, load: () => Promise<T>, force: boolean): Promise<T> {
  const hit = cache.get(key);
  if (!force && hit && Date.now() - hit.at < TTL_MS) return hit.promise as Promise<T>;

  const promise = load();
  cache.set(key, { at: Date.now(), promise });
  // Never keep a failure: the next caller retries.
  promise.catch(() => {
    if (cache.get(key)?.promise === promise) cache.delete(key);
  });
  return promise;
}

/** Units of measure are platform-wide reference data. */
export function getUnits(force = false): Promise<UnitOfMeasure[]> {
  return cached("units", () => apiRequest<UnitOfMeasure[]>("/api/v1/units"), force);
}

export function getCategories(tenantId: string, force = false): Promise<Category[]> {
  return cached(`categories:${tenantId}`, () => apiRequest<Category[]>("/api/v1/categories"), force);
}

export function getBrands(tenantId: string, force = false): Promise<Brand[]> {
  return cached(`brands:${tenantId}`, () => apiRequest<Brand[]>("/api/v1/brands"), force);
}

/** Forget everything, e.g. on sign-out, so the next user starts clean. */
export function clearReferenceCache(): void {
  cache.clear();
}
