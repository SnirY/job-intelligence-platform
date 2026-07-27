"use client";

import {
  EMPLOYMENT_TYPE_LABELS,
  JOB_SORT_LABELS,
  SENIORITY_LABELS,
  WORK_MODE_LABELS,
  type ArchivedFilter,
  type JobListQuery,
  type JobSort,
} from "@jip/shared-types";
import { Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

interface JobFiltersProps {
  query: JobListQuery;
  companies: string[];
  onChange: (next: Partial<JobListQuery>) => void;
  onReset: () => void;
}

/**
 * Search, filters, and sort for the job list.
 *
 * The filters `docs/08-ui-ux.md` lists that depend on match scores,
 * recommendations, or application status are absent: none of those exist yet,
 * and a filter that silently matches nothing reads as a broken product rather
 * than an unbuilt one.
 */
export function JobFilters({ query, companies, onChange, onReset }: JobFiltersProps) {
  const hasFilters = Boolean(
    query.search ||
    query.company ||
    query.work_mode ||
    query.employment_type ||
    query.seniority ||
    (query.archived && query.archived !== "ACTIVE"),
  );

  return (
    <div className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1 space-y-2">
          <Label htmlFor="job-search">Search</Label>
          <div className="relative">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              id="job-search"
              className="pl-9"
              placeholder="Title, company, location, or description"
              value={query.search ?? ""}
              onChange={(event) => onChange({ search: event.target.value, page: 1 })}
            />
          </div>
        </div>

        <div className="space-y-2 sm:w-48">
          <Label htmlFor="job-sort">Sort</Label>
          <Select
            id="job-sort"
            value={query.sort ?? "NEWEST"}
            onChange={(event) => onChange({ sort: event.target.value as JobSort, page: 1 })}
          >
            {Object.entries(JOB_SORT_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-2">
          <Label htmlFor="job-company">Company</Label>
          <Select
            id="job-company"
            value={query.company ?? ""}
            onChange={(event) => onChange({ company: event.target.value, page: 1 })}
          >
            <option value="">Any company</option>
            {companies.map((company) => (
              <option key={company} value={company}>
                {company}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="job-work-mode">Work mode</Label>
          <Select
            id="job-work-mode"
            value={query.work_mode ?? ""}
            onChange={(event) =>
              onChange({ work_mode: event.target.value as JobListQuery["work_mode"], page: 1 })
            }
          >
            <option value="">Any work mode</option>
            {Object.entries(WORK_MODE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="job-employment-type">Employment type</Label>
          <Select
            id="job-employment-type"
            value={query.employment_type ?? ""}
            onChange={(event) =>
              onChange({
                employment_type: event.target.value as JobListQuery["employment_type"],
                page: 1,
              })
            }
          >
            <option value="">Any type</option>
            {Object.entries(EMPLOYMENT_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="job-archived">Show</Label>
          <Select
            id="job-archived"
            value={query.archived ?? "ACTIVE"}
            onChange={(event) =>
              onChange({ archived: event.target.value as ArchivedFilter, page: 1 })
            }
          >
            <option value="ACTIVE">Active jobs</option>
            <option value="ARCHIVED">Archived</option>
            <option value="ALL">Everything</option>
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="space-y-2">
          <Label htmlFor="job-seniority" className="sr-only">
            Seniority
          </Label>
          <Select
            id="job-seniority"
            className="w-48"
            value={query.seniority ?? ""}
            onChange={(event) =>
              onChange({ seniority: event.target.value as JobListQuery["seniority"], page: 1 })
            }
          >
            <option value="">Any seniority</option>
            {Object.entries(SENIORITY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>

        {hasFilters && (
          <Button type="button" variant="ghost" size="sm" onClick={onReset}>
            <X aria-hidden className="size-4" />
            Clear filters
          </Button>
        )}
      </div>
    </div>
  );
}
