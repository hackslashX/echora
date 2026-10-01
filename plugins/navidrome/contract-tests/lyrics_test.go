package contracttests

import (
	"context"
	"os"
	"testing"

	"github.com/navidrome/navidrome/model"
)

func TestEchoraTTML(t *testing.T) {
	contents, err := os.ReadFile("testdata/lyrics.ttml")
	if err != nil {
		t.Fatal(err)
	}
	// Plugins provide raw text without a suffix. Exercise content detection too.
	tracks, err := model.ParseLyrics(context.Background(), "", "en", contents)
	if err != nil {
		t.Fatal(err)
	}
	if len(tracks) != 2 {
		t.Fatalf("expected main and translation, got %+v", tracks)
	}
	main, ok := tracks.Main()
	if !ok || main.Lang != "en" || !main.Synced || len(main.Line) != 2 {
		t.Fatalf("bad main track: %+v", main)
	}
	first := main.Line[0]
	if first.Value != "Hello & world" || *first.Start != 1000 || *first.End != 3000 || len(first.Cue) != 2 {
		t.Fatalf("bad first line: %+v", first)
	}
	if *first.Cue[0].Start != 1000 || *first.Cue[0].End != 2000 || *first.Cue[1].Start != 2000 {
		t.Fatalf("bad syllable timing: %+v", first.Cue)
	}
	if main.Line[1].Value != "こんにちは" {
		t.Fatalf("lost unicode: %+v", main.Line[1])
	}
	translation := tracks[1]
	if translation.Kind != model.LyricKindTranslation || translation.Lang != "es" || len(translation.Line) != 2 {
		t.Fatalf("bad translation: %+v", translation)
	}
	if translation.Line[0].Value != "Hola & mundo" || *translation.Line[0].Start != 1000 || *translation.Line[0].End != 3000 {
		t.Fatalf("bad translated line mapping: %+v", translation.Line[0])
	}
}

func TestEchoraLRC(t *testing.T) {
	contents, err := os.ReadFile("testdata/lyrics.lrc")
	if err != nil {
		t.Fatal(err)
	}
	tracks, err := model.ParseLyrics(context.Background(), "", "en", contents)
	if err != nil {
		t.Fatal(err)
	}
	main, ok := tracks.Main()
	if !ok || !main.Synced || len(main.Line) != 2 || main.Line[0].Value != "Hello & world" || *main.Line[0].Start != 1000 || main.Line[1].Value != "こんにちは" {
		t.Fatalf("bad LRC: %+v", tracks)
	}
}
