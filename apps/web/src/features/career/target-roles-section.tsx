"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  SENIORITY_LABELS,
  type Seniority,
  type TargetRole,
  type TargetRoleCreate,
} from "@jip/shared-types";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldHint, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  createTargetRole,
  deleteTargetRole,
  fetchTargetRoles,
  targetRolesQueryKey,
  updateTargetRole,
} from "@/features/career/api";
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const SENIORITIES = Object.keys(SENIORITY_LABELS) as Seniority[];

const EMPTY_DRAFT: TargetRoleCreate = {
  title: "",
  role_family: "",
  desired_seniority: null,
  priority: 1,
};

export function TargetRolesSection() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<TargetRoleCreate>(EMPTY_DRAFT);

  const {
    data: roles,
    isPending,
    error,
  } = useQuery({
    queryKey: targetRolesQueryKey,
    queryFn: () => fetchTargetRoles(api),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: targetRolesQueryKey });

  const addRole = useMutation({
    mutationFn: (body: TargetRoleCreate) => createTargetRole(api, body),
    onSuccess: async () => {
      setDraft(EMPTY_DRAFT);
      await invalidate();
    },
  });

  const toggleActive = useMutation({
    mutationFn: (role: TargetRole) =>
      updateTargetRole(api, role.id, { is_active: !role.is_active }),
    onSuccess: invalidate,
  });

  const removeRole = useMutation({
    mutationFn: (role: TargetRole) => deleteTargetRole(api, role.id),
    onSuccess: invalidate,
  });

  const titleIsBlank = draft.title.trim() === "";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Target roles</CardTitle>
        <CardDescription>
          What you are aiming for. These decide which opportunities are worth your attention.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {error ? (
          <p className="text-sm text-destructive">
            {error instanceof ApiError && error.isUnauthenticated
              ? "Your session was not accepted. Try signing out and back in."
              : "Could not load your target roles."}
          </p>
        ) : isPending ? (
          <p className="text-sm text-muted-foreground">Loading target roles…</p>
        ) : roles.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No target roles yet. Add the first one below to start shaping what the platform looks
            for.
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {roles.map((role) => (
              <li key={role.id} className="flex flex-wrap items-center gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{role.title}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {[
                      role.role_family,
                      role.desired_seniority ? SENIORITY_LABELS[role.desired_seniority] : null,
                      `Priority ${role.priority}`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>

                <Badge variant={role.is_active ? "success" : "secondary"}>
                  {role.is_active ? "Active" : "Paused"}
                </Badge>

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={toggleActive.isPending}
                  onClick={() => toggleActive.mutate(role)}
                >
                  {role.is_active ? "Pause" : "Resume"}
                </Button>

                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${role.title}`}
                  disabled={removeRole.isPending}
                  onClick={() => removeRole.mutate(role)}
                >
                  <Trash2 aria-hidden className="size-4" />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <form
          className="space-y-4 border-t pt-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (titleIsBlank) return;
            addRole.mutate({
              ...draft,
              title: draft.title.trim(),
              role_family: draft.role_family?.trim() || null,
            });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="role-title">Role title</Label>
              <Input
                id="role-title"
                value={draft.title}
                maxLength={200}
                placeholder="Backend Engineer"
                onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="role-family">Role family</Label>
              <Input
                id="role-family"
                value={draft.role_family ?? ""}
                maxLength={100}
                placeholder="Backend"
                onChange={(event) => setDraft({ ...draft, role_family: event.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="role-seniority">Desired seniority</Label>
              <select
                id="role-seniority"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                value={draft.desired_seniority ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    desired_seniority: (event.target.value || null) as Seniority | null,
                  })
                }
              >
                <option value="">Not specified</option>
                {SENIORITIES.map((level) => (
                  <option key={level} value={level}>
                    {SENIORITY_LABELS[level]}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="role-priority">Priority</Label>
              <Input
                id="role-priority"
                type="number"
                min={0}
                max={1000}
                value={draft.priority ?? 1}
                onChange={(event) =>
                  setDraft({ ...draft, priority: Number(event.target.value) || 0 })
                }
              />
              <FieldHint>Lower comes first.</FieldHint>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={titleIsBlank || addRole.isPending}>
              <Plus aria-hidden className="size-4" />
              {addRole.isPending ? "Adding…" : "Add target role"}
            </Button>

            <p aria-live="polite" className="text-sm">
              {addRole.isError && (
                <span className="text-destructive">
                  {addRole.error instanceof ApiError && addRole.error.status === 409
                    ? "You already have a target role with that title."
                    : "Could not add that target role."}
                </span>
              )}
              {removeRole.isError && (
                <span className="text-destructive">Could not remove that target role.</span>
              )}
            </p>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
