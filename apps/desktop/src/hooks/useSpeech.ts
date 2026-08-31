import { useCallback, useEffect, useRef, useState } from "react";
import { agentTauriService } from "@/services/agentTauriService";

/** Minimal typings for the Web Speech API (not in the DOM lib by default). */
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
}

type RecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): RecognitionCtor | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const synthSupported = typeof window !== "undefined" && "speechSynthesis" in window;
const remoteTtsSupported = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
const recognitionSupported = typeof window !== "undefined" && !!getRecognitionCtor();

/**
 * Web Speech API wrapper: speech-to-text (recognition) + text-to-speech
 * (synthesis). Both feature-detect and degrade gracefully — on platforms
 * where recognition is unavailable (some WebView2 builds), `sttSupported` is
 * false and the listening calls no-op.
 */
export function useSpeech() {
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speechRequestRef = useRef(0);
  // Latest callback for final transcripts, kept in a ref so handlers stay stable.
  const onFinalRef = useRef<(text: string) => void>(() => {});

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
  }, []);

  /** Start dictation. `onFinal` fires with each finalized transcript chunk.
   * `continuous` keeps the mic open until `stopListening` (used by STT toggle
   * and voice-loop); false auto-stops after one utterance (push-to-talk). */
  const startListening = useCallback(
    (onFinal: (text: string) => void, opts?: { continuous?: boolean }) => {
      const Ctor = getRecognitionCtor();
      if (!Ctor) return false;
      // Restart cleanly if already running.
      recognitionRef.current?.abort();

      const rec = new Ctor();
      rec.lang = navigator.language || "en-US";
      rec.continuous = opts?.continuous ?? true;
      rec.interimResults = true;
      onFinalRef.current = onFinal;

      rec.onresult = (e: any) => {
        let finalText = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          if (res.isFinal) finalText += res[0].transcript;
        }
        if (finalText.trim()) onFinalRef.current(finalText.trim());
      };
      rec.onerror = () => setListening(false);
      rec.onend = () => {
        setListening(false);
        recognitionRef.current = null;
      };

      recognitionRef.current = rec;
      try {
        rec.start();
        setListening(true);
        return true;
      } catch {
        setListening(false);
        return false;
      }
    },
    [],
  );

  const cancelSpeak = useCallback(() => {
    speechRequestRef.current += 1;
    audioRef.current?.pause();
    audioRef.current = null;
    if (synthSupported) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  /** Speak `text` aloud, cancelling anything already in progress. */
  const speak = useCallback(
    async (text: string) => {
      const input = text.trim();
      if ((!remoteTtsSupported && !synthSupported) || !input) return;
      const requestId = ++speechRequestRef.current;
      audioRef.current?.pause();
      audioRef.current = null;
      if (synthSupported) window.speechSynthesis.cancel();
      setSpeaking(true);
      if (remoteTtsSupported) {
        try {
          const result = await agentTauriService.synthesizeSpeech(input);
          if (speechRequestRef.current !== requestId) return;
          const audio = new Audio(result.data_url);
          audioRef.current = audio;
          audio.onended = () => {
            if (speechRequestRef.current === requestId) setSpeaking(false);
          };
          audio.onerror = () => {
            if (speechRequestRef.current === requestId) setSpeaking(false);
          };
          await audio.play();
          return;
        } catch {
          // Fall through to local synthesis when no remote key is configured.
        }
      }
      if (speechRequestRef.current !== requestId || !synthSupported) {
        setSpeaking(false);
        return;
      }
      const utter = new SpeechSynthesisUtterance(input);
      utter.lang = navigator.language || "en-US";
      utter.onend = () => setSpeaking(false);
      utter.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utter);
    },
    [],
  );

  // Stop the mic / voice on unmount so nothing keeps running off-screen.
  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      speechRequestRef.current += 1;
      audioRef.current?.pause();
      if (synthSupported) window.speechSynthesis.cancel();
    };
  }, []);

  return {
    sttSupported: recognitionSupported,
    ttsSupported: remoteTtsSupported || synthSupported,
    listening,
    speaking,
    startListening,
    stopListening,
    speak,
    cancelSpeak,
  };
}
