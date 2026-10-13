import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Solo preferencias de accesibilidad, no sensibles: nunca expedientes, ofertas, decisiones ni permisos.
export interface Preferences {
  bigText: boolean;
  highContrast: boolean;
  reduceMotion: boolean;
  setPref: (key: 'bigText' | 'highContrast' | 'reduceMotion', value: boolean) => void;
}

export const usePreferences = create<Preferences>()(
  persist(
    (set) => ({
      bigText: false,
      highContrast: false,
      reduceMotion: false,
      setPref: (key, value) => set({ [key]: value } as Partial<Preferences>),
    }),
    {
      name: 'compra-clara-preferencias',
      partialize: (s) => ({ bigText: s.bigText, highContrast: s.highContrast, reduceMotion: s.reduceMotion }),
    },
  ),
);