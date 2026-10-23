import { Monitor } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useSessionStore } from '@/stores/sessionStore'

interface FooterProps {
  className?: string
}

export function Footer({ className }: FooterProps) {
  const [version, setVersion] = useState<string>('')
  const activeSessionCount = useSessionStore((s) => s.activeSessionCount)

  useEffect(() => {
    const fetchVersion = async () => {
      try {
        const response = await fetch('/auth/app-info')
        const data = await response.json()
        if (data.status === 'success') {
          setVersion(data.version)
        }
      } catch (_error) {}
    }

    fetchVersion()
  }, [])

  return (
    <footer className={cn('mt-auto border-t bg-muted/30', className)}>
      <div className="container mx-auto px-4 py-6">
        <div className="flex flex-col md:flex-row items-center justify-center gap-2 md:gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>Copyright 2026</span>
            <span className="hidden md:inline">|</span>
            <a
              href="https://algo.domainxpert.in/"
              className="text-primary hover:underline font-medium"
              target="_blank"
              rel="noopener noreferrer"
            >
              DomainXpert Trade
            </a>
          </div>
          <span className="text-center">Your trading workspace</span>
          {version && (
            <>
              <span className="hidden md:inline">|</span>
              <Badge variant="secondary" className="gap-1">
                <span className="opacity-75">v</span>
                <span>{version}</span>
              </Badge>
            </>
          )}
          {activeSessionCount > 0 && (
            <>
              <span className="hidden md:inline">|</span>
              <Badge variant="outline" className="gap-1">
                <Monitor className="h-3 w-3" />
                <span>
                  {activeSessionCount} {activeSessionCount === 1 ? 'session' : 'sessions'}
                </span>
              </Badge>
            </>
          )}
        </div>

        <details className="mx-auto mt-4 max-w-xl text-center text-xs text-muted-foreground">
          <summary className="cursor-pointer">Source &amp; licenses</summary>
          <div className="mt-3 space-y-2 leading-relaxed">
            <p>
              DomainXpert Trade includes modified OpenAlgo software. Original copyright notices are
              retained in the source. Modifications include branding, account isolation, paper
              previews and subscription preview.
            </p>
            <p>
              Licensed under GNU AGPL v3. You may copy, modify and redistribute the covered software
              under its license. It is provided without warranty, except where separately agreed.
            </p>
            <p>
              <a
                href="https://github.com/virendrapal37vs/domainexpert/tree/feature/multi-user"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                View and download source
              </a>{' '}
              ·{' '}
              <a
                href="https://github.com/virendrapal37vs/domainexpert/blob/feature/multi-user/License.md"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                Read the license
              </a>
            </p>
          </div>
        </details>
      </div>
    </footer>
  )
}
