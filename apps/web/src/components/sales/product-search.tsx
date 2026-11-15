"use client";

import { ScanBarcode } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { controlClass } from "@/components/ui/field";
import { apiRequest } from "@/lib/api";
import { formatMoney, formatQuantity } from "@/lib/catalog";
import type { Product, ProductList } from "@/lib/types";
import { cn } from "@/lib/utils";

const search = (q: string) =>
  apiRequest<ProductList>(
    `/api/v1/products?${new URLSearchParams({ q, status: "active", page_size: "8" }).toString()}`,
  ).then((list) => list.items);

/**
 * Find a product by name, code or barcode. A barcode scanner types the code
 * and presses Enter: Enter searches at once and takes the exact barcode/code
 * match, otherwise the highlighted result.
 */
export function ProductSearch({ onPick }: { onPick: (product: Product) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [notFound, setNotFound] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  useEffect(() => {
    const term = query.trim();
    if (!term) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      search(term)
        .then((items) => {
          if (cancelled) return;
          setResults(items);
          setActive(0);
          setOpen(true);
        })
        .catch(() => undefined);
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  const pick = (product: Product) => {
    onPick(product);
    setQuery("");
    setResults([]);
    setOpen(false);
    setNotFound(null);
    inputRef.current?.focus();
  };

  const onEnter = async () => {
    const term = query.trim();
    if (!term) return;
    const items = await search(term).catch(() => results);
    const lowered = term.toLowerCase();
    const exact = items.find(
      (item) => item.barcode === term || item.sku.toLowerCase() === lowered,
    );
    const chosen = exact ?? (open ? items[active] ?? items[0] : items[0]);
    if (chosen) pick(chosen);
    else setNotFound(term);
  };

  return (
    <div className="relative">
      <label htmlFor={`${listId}-input`} className="sr-only">
        ابحث عن صنف بالاسم أو الكود أو الباركود
      </label>
      <ScanBarcode
        className="pointer-events-none absolute inset-y-0 start-3 my-auto size-5 text-ink-muted"
        aria-hidden="true"
      />
      <input
        ref={inputRef}
        id={`${listId}-input`}
        type="search"
        autoFocus
        autoComplete="off"
        enterKeyHint="go"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        aria-activedescendant={open && results[active] ? `${listId}-${results[active].id}` : undefined}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setNotFound(null);
          if (!event.target.value.trim()) {
            setResults([]);
            setOpen(false);
          }
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void onEnter();
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((index) => Math.min(index + 1, results.length - 1));
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((index) => Math.max(index - 1, 0));
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder="اكتب اسم الصنف أو امسح الباركود"
        className={cn(controlClass, "min-h-12 ps-11 text-base")}
      />
      {notFound ? (
        <p role="status" className="mt-1.5 text-xs text-red-700">
          لا يوجد صنف نشط بهذا الاسم أو الكود: «{notFound}»
        </p>
      ) : null}
      {open && results.length > 0 ? (
        <ul
          id={listId}
          role="listbox"
          aria-label="نتائج البحث"
          className="absolute inset-x-0 top-full z-30 mt-1 max-h-80 overflow-y-auto rounded-md border border-line bg-white py-1 shadow-lg"
        >
          {results.map((product, index) => (
            <li
              key={product.id}
              id={`${listId}-${product.id}`}
              role="option"
              aria-selected={index === active}
              onMouseDown={(event) => {
                event.preventDefault();
                pick(product);
              }}
              onMouseEnter={() => setActive(index)}
              className={cn(
                "flex cursor-pointer items-center gap-3 px-3 py-2 text-sm",
                index === active ? "bg-brand-50" : "hover:bg-surface",
              )}
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-ink">{product.name_ar}</span>
                <span className="block text-xs text-ink-muted" dir="ltr">
                  {product.sku}
                </span>
              </span>
              <span className="text-end text-xs text-ink-muted">
                <span className="block font-medium text-ink">
                  {product.sale_price ? formatMoney(product.sale_price) : "بلا سعر"}
                </span>
                متوفر {formatQuantity(product.stock_quantity)} {product.base_unit_name_ar}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
