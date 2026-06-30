import { useState } from "react";
import { useForm } from "react-hook-form";
import { LogIn } from "lucide-react";
import { useAdminAuthStore } from "@/stores/useAdminAuthStore";
import { apiClient, ApiCallFailed } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type LoginForm = { password: string };

/**
 * Tiny "auth" form. The password is sent as the x-admin-password
 * header on every admin call. Server-side compare is constant-time.
 * Storing the password in localStorage is documented as not-real-auth
 * (AGENT-frontend.md §13.3).
 */
export function AdminLogin() {
  const setPassword = useAdminAuthStore((s) => s.setPassword);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { register, handleSubmit } = useForm<LoginForm>({
    defaultValues: { password: "" },
  });

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    setIsSubmitting(true);
    try {
      // Validate the password by hitting /summary. If 401, we surface
      // the error; if 200, we save the password and let the parent
      // re-render the dashboard.
      await apiClient.getAdminSummary(data.password, 1);
      setPassword(data.password);
    } catch (err) {
      if (err instanceof ApiCallFailed && err.apiError.code === "admin_auth_failed") {
        setError("Incorrect password.");
      } else {
        setError(err instanceof Error ? err.message : "Unexpected error");
      }
    } finally {
      setIsSubmitting(false);
    }
  });

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle>Admin login</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(e) => {
            void onSubmit(e);
          }}
          className="space-y-4"
        >
          <div>
            <label htmlFor="admin-password" className="text-sm font-medium">
              Password
            </label>
            <Input
              id="admin-password"
              type="password"
              autoComplete="current-password"
              {...register("password", { required: true })}
            />
          </div>
          {error !== null && (
            <Alert variant="destructive">
              <AlertTitle>Login failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={isSubmitting} className="w-full">
            <LogIn className="h-4 w-4" />
            {isSubmitting ? "Checking..." : "Sign in"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
