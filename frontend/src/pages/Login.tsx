import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export default function Login() {
  useDocumentTitle('CRM - Login')
  const navigate = useNavigate()
  const setAuth = useAuthStore((state) => state.setAuth)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setLoading(true)
    setError('')

    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      if (!response.ok) {
        throw new Error('Invalid email or password')
      }

      const data: { access_token: string } = await response.json()
      setAuth(data.access_token)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-6">
      <div className="w-full max-w-md rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
        <p className="mb-1.5 text-sm uppercase tracking-[0.35em] text-cyan-600">CRM Access</p>
        <h2 className="text-3xl font-semibold text-gray-900">Sign in</h2>
        <p className="mt-1.5 text-sm text-gray-500">Use your CRM credentials to continue.</p>

        <form className="mt-4 space-y-3" onSubmit={handleSubmit}>
          <div>
            <label className="mb-1.5 block text-sm text-gray-700">Email</label>
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" className="w-full rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-gray-900 outline-none ring-0 placeholder:text-gray-400 focus:border-cyan-500" placeholder="you@company.com" required />
          </div>

          <div>
            <label className="mb-1.5 block text-sm text-gray-700">Password</label>
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" className="w-full rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-gray-900 outline-none ring-0 placeholder:text-gray-400 focus:border-cyan-500" required />
          </div>

          {error ? <p className="text-sm text-rose-400">{error}</p> : null}

          <button type="submit" disabled={loading} className="w-full rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-70">
            {loading ? 'Signing in...' : 'Login'}
          </button>
        </form>
      </div>
    </main>
  )
}
