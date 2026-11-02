import type { Locale } from '../i18n';

export type CropCategory = 'legumes' | 'cereales' | 'fruits';
export interface Crop { id: string; category: CropCategory; names: Record<Locale, string> }

/**
 * Les cultures suivies par la ferme (le même catalogue que le tableau de bord).
 * Pour le lingala, les noms courants à Kinshasa sont souvent les mêmes qu'en français : ils sont gardés tels quels
 * quand on n'est pas certain d'un mot lingala. À faire relire par un locuteur.
 */
export const crops: Crop[] = [
  { id: 'tomate', category: 'legumes', names: { fr: 'Tomate', en: 'Tomato', ln: 'Tomate', sw: 'Nyanya' } },
  { id: 'piment', category: 'legumes', names: { fr: 'Piment', en: 'Chili pepper', ln: 'Pilipili', sw: 'Pilipili' } },
  { id: 'poivron', category: 'legumes', names: { fr: 'Poivron', en: 'Bell pepper', ln: 'Poivron', sw: 'Pilipili hoho' } },
  { id: 'aubergine', category: 'legumes', names: { fr: 'Aubergine', en: 'Eggplant', ln: 'Aubergine', sw: 'Biringanya' } },
  { id: 'gombo', category: 'legumes', names: { fr: 'Gombo', en: 'Okra', ln: 'Gombo', sw: 'Bamia' } },
  { id: 'amarante', category: 'legumes', names: { fr: 'Amarante (loso)', en: 'Amaranth (loso)', ln: 'Loso', sw: 'Mchicha' } },
  { id: 'chou', category: 'legumes', names: { fr: 'Chou', en: 'Cabbage', ln: 'Chou', sw: 'Kabichi' } },
  { id: 'mais', category: 'cereales', names: { fr: 'Maïs', en: 'Maize', ln: 'Maïs', sw: 'Mahindi' } },
  { id: 'manioc', category: 'cereales', names: { fr: 'Manioc', en: 'Cassava', ln: 'Manioc', sw: 'Muhogo' } },
  { id: 'patate', category: 'cereales', names: { fr: 'Patate douce', en: 'Sweet potato', ln: 'Patate douce', sw: 'Viazi vitamu' } },
  { id: 'arachide', category: 'cereales', names: { fr: 'Arachide', en: 'Groundnut', ln: 'Arachide', sw: 'Karanga' } },
  { id: 'papaye', category: 'fruits', names: { fr: 'Papaye', en: 'Papaya', ln: 'Papaye', sw: 'Papai' } },
  { id: 'banane', category: 'fruits', names: { fr: 'Banane et plantain', en: 'Banana and plantain', ln: 'Banane', sw: 'Ndizi' } },
  { id: 'avocat', category: 'fruits', names: { fr: 'Avocatier', en: 'Avocado', ln: 'Avocat', sw: 'Parachichi' } },
  { id: 'palmier', category: 'fruits', names: { fr: 'Palmier à huile', en: 'Oil palm', ln: 'Palmier à huile', sw: 'Mchikichi' } },
];
