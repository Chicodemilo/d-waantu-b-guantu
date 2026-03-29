import Sidebar from './Sidebar';
import Header from './Header';
import Footer from './Footer';
import '../../styles/layout.css';

function AppShell({ children }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <Header />
      <main className="main-content">{children}</main>
      <Footer />
    </div>
  );
}

export default AppShell;
