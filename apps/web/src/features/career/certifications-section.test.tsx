import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CertificationsSection } from "@/features/career/certifications-section";

const getToken = vi.fn<() => Promise<string | null>>().mockResolvedValue("token");

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken }),
}));

function jsonResponse(data: unknown) {
  return { ok: true, status: 200, json: async () => ({ data }) };
}

function renderSection(ui: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const AWS = {
  id: "c1",
  name: "AWS Certified Solutions Architect",
  issuer: "Amazon Web Services",
  issued_on: "2023-05-01",
  expires_on: "2030-05-01",
  credential_id: "ABCD-1234",
  credential_url: null,
  description: null,
  verification_status: "USER_CONFIRMED",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CertificationsSection", () => {
  it("lists what is on file", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([AWS])));

    renderSection(<CertificationsSection />);

    expect(await screen.findByText("AWS Certified Solutions Architect")).toBeInTheDocument();
    expect(screen.getByText(/Amazon Web Services/)).toBeInTheDocument();
  });

  it("marks a lapsed credential and leaves a permanent one alone", async () => {
    // A null expiry means "does not expire", never "expiry unknown" — the same
    // reading the matcher uses. Inverted, this badge would call every permanent
    // credential expired.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse([
          { ...AWS, id: "c1", name: "Lapsed cert", expires_on: "2020-01-01" },
          { ...AWS, id: "c2", name: "Permanent cert", expires_on: null },
        ]),
      ),
    );

    renderSection(<CertificationsSection />);
    await screen.findByText("Lapsed cert");

    expect(screen.getAllByText("Expired")).toHaveLength(1);
    expect(screen.getByText(/no expiry/)).toBeInTheDocument();
  });

  it("posts a trimmed certification", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse(AWS))
      .mockResolvedValue(jsonResponse([AWS]));
    vi.stubGlobal("fetch", fetchMock);

    renderSection(<CertificationsSection />);
    await userEvent.type(await screen.findByLabelText("Certification"), "  PMP  ");
    await userEvent.type(screen.getByLabelText("Issuer"), " PMI ");
    await userEvent.click(screen.getByRole("button", { name: /Add certification/ }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (call) => (call[1] as RequestInit | undefined)?.method === "POST",
      );
      expect(post).toBeDefined();
      const body = JSON.parse((post![1] as RequestInit).body as string) as Record<string, unknown>;
      expect(body.name).toBe("PMP");
      expect(body.issuer).toBe("PMI");
      expect(body.expires_on).toBeNull();
    });
  });

  it("will not save without both a name and an issuer", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));

    renderSection(<CertificationsSection />);
    await userEvent.type(await screen.findByLabelText("Certification"), "PMP");

    expect(screen.getByRole("button", { name: /Add certification/ })).toBeDisabled();
  });

  it("refuses an expiry that precedes the issue date, and says why", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));

    renderSection(<CertificationsSection />);
    await userEvent.type(await screen.findByLabelText("Certification"), "PMP");
    await userEvent.type(screen.getByLabelText("Issuer"), "PMI");
    await userEvent.type(screen.getByLabelText("Issued on"), "2025-01-01");
    await userEvent.type(screen.getByLabelText("Expires on"), "2024-01-01");

    expect(await screen.findByText(/expiry date is before the issue date/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add certification/ })).toBeDisabled();
  });

  it("says so when the list cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    renderSection(<CertificationsSection />);

    expect(await screen.findByText(/Could not load certifications/)).toBeInTheDocument();
  });
});
