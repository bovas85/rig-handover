import type { DigestNight } from '../digest/types.js';

export function DigestView({ digest }: { digest: DigestNight }) {
  return (
    <>
      <h1>digest · {digest.night}</h1>
      {digest.rows.length === 0 ? (
        <p class="mute">nothing ran</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>job</th>
              <th>owner</th>
              <th>runs</th>
              <th>retries</th>
              <th>status</th>
              <th>last error</th>
              <th>times</th>
            </tr>
          </thead>
          <tbody>
            {digest.rows.map((row) => (
              <tr>
                <td>{row.job}</td>
                <td>{row.owner}</td>
                <td>{row.runs}</td>
                <td class={row.retries >= 3 ? 'warn' : ''}>{row.retries}</td>
                <td class={row.lastStatus === 'fail' ? 'warn' : ''}>
                  {row.lastStatus}
                </td>
                <td class={row.lastError ? 'warn' : 'mute'}>
                  {row.lastError ?? '—'}
                </td>
                <td class="mute">
                  {row.firstTime === row.lastTime
                    ? row.firstTime
                    : `${row.firstTime} … ${row.lastTime}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {digest.badLines > 0 && (
        <p class="mute">
          {digest.badLines} bad {digest.badLines === 1 ? 'line' : 'lines'}{' '}
          skipped
        </p>
      )}
    </>
  );
}
