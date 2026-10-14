import "./globals.css";
import NavBar from "./nav-bar";

export const metadata = {
  title: "University Document Portal",
  description:
    "Request academic documents online: submit an application, upload supporting documents, and track its progress.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <NavBar />
        <div className="page">{children}</div>
        <footer className="site-footer">
          <div className="container">
            <p>
              <strong>University Document Portal</strong> — an academic project prototype.
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
