import { Suspense } from "react";

import { SignupForm } from "./signup-form";

export default function SignupPage() {
  return (
    <div className="container mx-auto flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-12">
      <Suspense>
        <SignupForm />
      </Suspense>
    </div>
  );
}
