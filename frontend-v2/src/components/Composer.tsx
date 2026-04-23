import { useState } from 'react'

interface ComposerProps {
  onSend: (content: string) => void
}

export function Composer({ onSend }: ComposerProps) {
  const [value, setValue] = useState('')

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const content = value.trim()
    if (!content) return
    onSend(content)
    setValue('')
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask Owlynn..."
        rows={3}
      />
      <button type="submit">Send</button>
    </form>
  )
}
