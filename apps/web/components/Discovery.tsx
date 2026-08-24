"use client";

import { FormEvent, useState } from "react";

const suggestions = ["midnight blues", "melancholy, but not hopeless", "late-night drive", "soft songs with devastating lyrics"];
const tracks = [
  { title: "Retrograde", artist: "James Blake", score: 96, hue: "#e88863" },
  { title: "Myth", artist: "Beach House", score: 92, hue: "#8989dc" },
  { title: "The Rip", artist: "Portishead", score: 89, hue: "#6aa69d" },
];

function WaveMark({ active = false }: { active?: boolean }) {
  return <div className={`wave-mark ${active ? "active" : ""}`} aria-hidden="true">
    {Array.from({ length: 17 }, (_, index) => <i key={index} style={{ "--i": index } as React.CSSProperties} />)}
  </div>;
}

export default function Discovery() {
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState(false);
  const [listening, setListening] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim()) setSearched(true);
  }

  return <main>
    <nav>
      <a className="brand" href="#">echora<span>.</span></a>
      <div className="nav-links"><button className="selected">Discover</button><button>Library</button><button>Evaluate</button></div>
      <button className="avatar" aria-label="Settings">HS</button>
    </nav>

    <section className={`hero ${searched ? "compact" : ""}`}>
      <div className="ambient" aria-hidden="true"><b /><b /><b /></div>
      <div className="eyebrow"><span /> Your library, understood</div>
      <h1>{searched ? <>This is what <em>that feeling</em> sounds like.</> : <>What do you want<br />to <em>feel?</em></>}</h1>
      <p>Describe a sound, a memory, or a mood. Echora searches the music you already love.</p>
      <form onSubmit={submit} className="search-box">
        <button type="button" className={`listen ${listening ? "on" : ""}`} onClick={() => setListening(!listening)} aria-label="Use voice input"><WaveMark active={listening} /></button>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Try “midnight blues with a pulse”" aria-label="Describe music" />
        <button className="arrow" aria-label="Search">↗</button>
      </form>
      {!searched && <div className="suggestions">{suggestions.map(item => <button key={item} onClick={() => setQuery(item)}>{item}</button>)}</div>}
    </section>

    {searched && <section className="results" aria-live="polite">
      <div className="result-head"><div><small>MATCHING YOUR LIBRARY</small><h2>Closest echoes</h2></div><button className="model">MuQ-MuLan <span>⌄</span></button></div>
      <div className="track-grid">
        {tracks.map((track, index) => <article key={track.title} style={{ "--tone": track.hue } as React.CSSProperties}>
          <div className="cover"><div className="rings" /><button aria-label={`Play ${track.title}`}>▶</button><span>{index + 1}</span></div>
          <div className="track-copy"><h3>{track.title}</h3><p>{track.artist}</p><div className="score"><i style={{ width: `${track.score}%` }} /><span>{track.score}% match</span></div></div>
        </article>)}
      </div>
      <button className="map-button">Explore these in the music map <span>→</span></button>
    </section>}

    <footer><span><i /> NAVIDROME CONNECTED</span><p>1,024 tracks · 3 models ready</p><button>Benchmark lab ↗</button></footer>
  </main>;
}
