/** Contracts for the current-user endpoint. */

/**
 * Payload of `GET /api/v1/users/me`.
 *
 * `id` is the platform's own identifier, not the authentication provider's.
 * The provider id is deliberately absent from the API surface.
 */
export interface CurrentUser {
  id: string;
  email: string | null;
  display_name: string | null;
  created_at: string;
}
