import { useStats } from '../../api/books';
import { Spinner } from '../common/Spinner';
import { formatBytes } from '../../utils/format';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';

const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#14b8a6'];

export function Dashboard() {
  const { data: stats, isLoading } = useStats();

  if (isLoading) return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  if (!stats) return null;

  const typeData = Object.entries(stats.by_type).map(([name, value]) => ({ name: name.toUpperCase(), value }));
  const statusData = Object.entries(stats.by_status).map(([name, value]) => ({
    name: name.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()), value,
  }));

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Library Statistics</h1>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Books" value={String(stats.total_books)} />
        <StatCard label="Total Size" value={formatBytes(stats.total_size_bytes)} />
        <StatCard label="With Covers" value={`${Math.round((stats.with_cover / stats.total_books) * 100)}%`} />
        <StatCard label="Avg Rating" value={stats.avg_rating ? `★ ${stats.avg_rating}` : '—'} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Categories chart */}
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
          <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">By Category</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={stats.categories.slice(0, 10)} layout="vertical">
              <XAxis type="number" />
              <YAxis type="category" dataKey="name" width={150} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* File type pie */}
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
          <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">By File Type</h2>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={typeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                {typeData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>

          <h2 className="mb-4 mt-6 text-sm font-bold text-slate-700 dark:text-slate-300">Reading Status</h2>
          <div className="space-y-2">
            {statusData.map((s, i) => (
              <div key={s.name} className="flex items-center gap-3">
                <div className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                <span className="flex-1 text-sm text-slate-600 dark:text-slate-400">{s.name}</span>
                <span className="text-sm font-bold text-slate-900 dark:text-white">{s.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Year histogram */}
        {stats.year_histogram.length > 0 && (
          <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700 lg:col-span-2">
            <h2 className="mb-4 text-sm font-bold text-slate-700 dark:text-slate-300">Publication Years</h2>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={stats.year_histogram}>
                <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                <YAxis />
                <Tooltip />
                <Bar dataKey="count" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
      <p className="text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
      <p className="text-sm text-slate-500">{label}</p>
    </div>
  );
}
