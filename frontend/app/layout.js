import "./globals.css";
import NavBar from "./nav-bar";

export const metadata = {
  title: "KLE Tech Student Document Portal",
  description:
    "Request academic documents online: submit an application, upload supporting documents, and track its progress.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      {/* kle-theme is applied here because every page in THIS frontend is student-facing;
          no admin UI lives in this app tree. Styles are scoped under .kle-theme in globals.css. */}
      <body className="kle-theme">
        <NavBar />
        <div className="page">{children}</div>
        <footer className="site-footer">
          <div className="container">
            <p>
              <strong>KLE Tech Student Document Portal</strong> — an academic project prototype.
            </p>
            <p>
              Student records are simulated and payments are sandbox-only. This is not an official
              university service.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
