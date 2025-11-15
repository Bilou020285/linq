# LinQ – Relations Explorer (QGIS plugin)

Un plugin pour **voir, comprendre et éditer** les relations d’un projet QGIS :
diagramme clair du modèle, colonnes d’entités, glisser-déposer pour créer/supprimer des liens (1↔N, N↔N), et exports (SVG, draw.io).

---

## Sommaire

- [Ce que fait LinQ](#ce-que-fait-linq)
- [Compatibilité & dépendances](#compatibilité--dépendances)
- [Installation](#installation)
- [Paramètres & astuces Graphviz](#paramètres--astuces-graphviz)
- [Prise en main rapide](#prise-en-main-rapide)
- [Diagramme de relations](#diagramme-de-relations)
- [Zone « Colonnes d’entités »](#zone--colonnes-dentités-)
- [Créer / supprimer des relations](#créer--supprimer-des-relations)
- [Édition et enregistrements](#édition-et-enregistrements)
- [Exports (SVG, draw.io)](#exports-svg-drawio)
- [Détection des tables de liaison (n↔n)](#détection-des-tables-de-liaison-nn)
- [Dépannage](#dépannage)
- [Limites connues](#limites-connues)

---

## Ce que fait LinQ

- **Analyse** les `QgsRelation` du projet (parents, enfants, paires **PK→FK**).
- **Affiche** un **diagramme** interactif :
  - boîtes **déplaçables** (les liens suivent),
  - **flèches** explicites parent → enfant,
  - **boucles** sur relations **réflexives**,
  - **double arête** si A↔B existe dans les deux sens,
  - clic-droit sur une arête : étiquette **Parent.Table.PK → Enfant.Table.FK**.
- **Édite les liens** via des **colonnes d’entités** :
  - sélection de tables, choix de l’**étiquette** (champ ou **expression QGIS** avec générateur),
  - **glisser-déposer** entre colonnes pour **lier** (1↔N) ou **créer** dans la **table de liaison** (N↔N),
  - **détacher** un enfant (met FK à `NULL`) ou **supprimer** la ligne de liaison (N↔N),
  - boutons **Tout replier / Tout déplier**, filtrage des enfants selon les tables chargées,
  - **Actualiser** pour recharger les entités (et **Vider** pour retirer les colonnes).
- **Exports** : **SVG** (diagramme Graphviz) et **draw.io** (boîtes « table » repliables à 2 colonnes).
  
> Remarque : pour N↔N avec plusieurs tables d’association possibles, LinQ propose un **menu** pour choisir la bonne table avant d’ouvrir son formulaire.

---

## Compatibilité & dépendances

- **QGIS** ≥ 3.22 (testé notamment en 3.44.x)
- **Python** 3.x, **PyQt5** (fournis par QGIS)
- **Graphviz** (`dot`) **optionnel mais recommandé** pour une mise en page nette

---

## Installation

- **Depuis QGIS** (recommandé) : *Extensions → Gérer et installer* → chercher **LinQ** → *Installer*.
- **Graphviz (conseillé)** :
  - Windows : `winget install Graphviz.Graphviz`
  - macOS : `brew install graphviz`
  - Debian/Ubuntu : `sudo apt install graphviz`

---

## Paramètres & astuces Graphviz

- LinQ tente de trouver `dot` via le **PATH**. Si besoin, indique le **chemin complet** dans le champ *Chemin vers dot* du panneau LinQ (ex. `C:\Program Files\Graphviz\bin\dot.exe`), puis clique **Enregistrer**.
- Relance **Analyser les relations** pour recalculer le placement.

---

## Prise en main rapide

1. Ouvre le **panneau LinQ** (menu Extensions / icône).
2. Si besoin, clique **Analyser les relations** (sinon le diagramme s’affiche automatiquement).
3. **Double-clic** sur une table du diagramme pour l’ajouter **en colonne** en bas.
4. Dans chaque colonne :
   - Choisis l’**étiquette** via l’entête (champ ou **[Expression QGIS…]** + bouton **fx**).
   - Utilise le **filtre** et le **tri**.
   - **Glisse-dépose** des entités vers une autre colonne pour créer la relation.
   - **Clic-droit** sur une entité enfant ⇒ **Détacher**.

---

## Diagramme de relations

- Boîtes = **nom de couche** QGIS (lisible), flèches **parent → enfant**.
- **Réflexif** : boucle sur la boîte ; **double sens** A↔B : deux arêtes décalées.
- **Clic-droit** sur une arête : affiche `Parent.Table.PK → Enfant.Table.FK`.
- **Recherche** (champ en haut à droite) pour focaliser des tables par nom.
- Le diagramme **met en avant** les tables ajoutées en colonnes (contexte visuel).

---

## Zone « Colonnes d’entités »

- **Ajouter** une colonne : **double-clic** dans le diagramme ou via *Table:* + **Ajouter colonne**.
- **Étiquettes** : champ simple ou **expression QGIS** (COALESCE, concat, etc.). Le **générateur** aide à construire l’expression.
- **Arborescences** : déplier pour voir les **enfants liés** ; boutons **Tout déplier / Tout replier**.
- **Filtrer enfants selon les tables chargées** : réduit l’affichage aux tables présentes en colonnes.
- **Actualiser** recharge la liste (utile après insertions / nouveaux liens).
- **Vider** retire toutes les colonnes.

---

## Créer / supprimer des relations

### 1↔N
- **Créer** : glisser l’**enfant** sur le **parent** (ou l’inverse ; LinQ identifie la relation).  
  → LinQ **renseigne la FK** de l’enfant.
- **Détacher** : clic-droit sur l’enfant → **Détacher** (FK mise à `NULL`).

### N↔N (table d’association)
- **Créer** : glisser une entité d’une table vers l’autre.  
  → Si plusieurs tables de liaison existent, LinQ te demande laquelle utiliser.  
  → LinQ **insère** la ligne dans la liaison, **préremplit les 2 FK**, et **ouvre le formulaire** si la table comporte d’autres champs.
- **Détacher** : LinQ **supprime** la ligne de liaison correspondante.

### Réflexif (A↔A)
- Nécessite deux relations distinctes (ex. `fk1`, `fk2`). LinQ remplit la bonne paire **PK↔FK**.

---

## Édition et enregistrements

- LinQ s’appuie sur les **boutons natifs QGIS** (*Activer l’édition*, *Enregistrer*, *Annuler*).
- Si nécessaire, LinQ propose d’**activer l’édition** sur les couches touchées.
- Après un glisser-déposer, LinQ affiche une **boîte de confirmation** listant précisément les **changements FK** (avec tes **étiquettes** d’entités) avant d’appliquer.
- Quand des modifications sont en attente, l’icône **crayon** de la colonne passe en **rouge**.  
  Enregistre ou annule pour revenir à l’état propre.

---

## Exports (SVG, draw.io)

- **Exporter diagramme (SVG)** : export Graphviz (pour doc/rapports).
- **Exporter Draw.io…** : génère un fichier **.drawio** où chaque table est un **swimlane repliable** avec **2 colonnes** (PK/FK à gauche, nom de champ souligné à droite).  
  Les arêtes portent l’étiquette `Parent.pk → Enfant.fk`.

---

## Détection des tables de liaison (n↔n)

- Heuristique actuelle : couche **enfant d’au moins 2 relations** vers **≥2 parents distincts**, et **PK ⊆ ensemble des FK**.
- (Visuel distinct non encore activé dans le diagramme ; l’information est utilisée pour l’assistant N↔N et l’export draw.io.)

---

## Dépannage

- **Graphviz non trouvé** : installe Graphviz, renseigne *Chemin vers dot*, relance **Analyser**.
- **Aucune relation détectée** : définis tes `QgsRelation` dans *Projet → Propriétés → Relations*.
- **Glisser-déposer sans effet** : vérifie l’**édition**, l’existence de la **relation**, et les contraintes (FK `NOT NULL`, triggers…).
- **Réflexif N↔N** : assure deux relations link→base distinctes (ex. `numfait1`/`numfait2`).
- **Nouvelle entité non visible** : clique **Actualiser** dans les colonnes.

---

## Limites connues

- Le layout dépend de Graphviz ; déplacer les boîtes ne recalcule pas la mise en page globale.
- Projets très volumineux : mise en page plus lente.
- Si plusieurs couches portent le **même nom**, préfère des noms distincts pour une meilleure lecture.

---

# LinQ – Relations Explorer (EN)

A QGIS plugin to **inspect and edit** project relations:
clean relationship diagram, entity columns, drag-and-drop to create/remove links (1↔N, N↔N), and exports (SVG, draw.io).

## What LinQ does

- **Parses** project `QgsRelation`s (parents, children, **PK→FK** pairs).
- **Shows** an **interactive diagram**:
  - **movable** boxes (edges follow),
  - explicit **arrows** parent → child,
  - **loops** for **self-relations**, **two edges** when both directions exist,
  - right-click on an edge: **Parent.Table.PK → Child.Table.FK** label.
- **Edits** links through **entity columns**:
  - pick tables, choose label (field or **QGIS expression** with expression builder),
  - **drag & drop** between columns to **link** (1↔N) or **insert** into the **link table** (N↔N),
  - **detach** a child (set FK to `NULL`) or **delete** the link row (N↔N),
  - expand/collapse all, option to filter children by loaded tables,
  - **Refresh** to reload entities, **Clear** to remove all columns.
- **Exports**: **SVG** (Graphviz) and **draw.io** (collapsible two-column table boxes).

## Compatibility & dependencies

- **QGIS** ≥ 3.22 (tested with 3.44.x)
- **Python** 3.x, **PyQt5** (bundled with QGIS)
- **Graphviz** (`dot`) **optional but recommended**

## Installation

- **From QGIS repository (recommended)**: *Plugins → Manage and Install* → search **LinQ** → *Install*.
- **Graphviz**:
  - Windows: `winget install Graphviz.Graphviz`
  - macOS: `brew install graphviz`
  - Debian/Ubuntu: `sudo apt install graphviz`

## Graphviz settings & tips

- If `dot` isn’t on PATH, set the full path in LinQ’s *Path to dot* field (e.g., `C:\Program Files\Graphviz\bin\dot.exe`), click **Save**, then **Analyze relations**.

## Quick start

1. Open the **LinQ panel**.
2. Click **Analyze relations** if needed.
3. **Double-click** a table in the diagram to add it as a **column**.
4. In columns: select label field or **QGIS expression** (with **fx**), filter/sort, and **drag & drop** to create links. Right-click a child to **Detach**.

## Diagram

- Boxes use layer **names**, arrows are **parent → child**.
- **Self-relation** ⇒ loop. **Both directions** ⇒ two offset edges.
- Right-click an edge to show `Parent.Table.PK → Child.Table.FK`.
- Search field focuses matching tables. Diagram highlights tables present in columns.

## Entity columns

- Add via **double-click** in diagram or using *Table:* + **Add column**.
- Labels: field or **QGIS expression** (expression builder available).
- Expand/collapse children; “Filter children by loaded tables” option.
- **Refresh** to reload; **Clear** to remove all columns.

## Create / remove relations

- **1↔N**: drag **child** to **parent** (or vice-versa). LinQ **sets the child FK**.  
  Detach with context menu (FK → `NULL`).
- **N↔N**: drag between tables. If multiple link tables exist, LinQ asks which one to use, **inserts** the row (both FKs prefilled), opens the **form** if extra fields exist.  
  Detach = **delete** link row.

## Editing & saving

- Uses **native QGIS** editing buttons. LinQ can enable editing when required.
- A **confirmation dialog** lists **exact FK changes** (with your labels) before applying.
- A **red pencil** indicates unsaved edits in a column.

## Exports

- **SVG** (Graphviz) and **draw.io**: tables are **collapsible swimlanes** with **two columns** (PK/FK on the left, underlined field names on the right).

## Link-table detection (n↔n)

- Heuristic: child in **≥2 relations** to **≥2 distinct parents**, and **PK ⊆ FKs**.  
  (Distinct visual styling in the diagram not enabled yet; used for helpers and draw.io export.)

## Troubleshooting

- Install Graphviz / set *Path to dot* / re-analyze.
- Ensure project **relations** are defined (Project → Properties → Relations).
- For drag-and-drop, ensure **editing** is enabled and DB constraints allow the change.
- For **self N↔N**, define two link→base relations (e.g., `fk1`, `fk2`).
- Use **Refresh** if new entities don’t show up.

## Known limitations

- Layout depends on Graphviz; moving boxes doesn’t recompute the whole layout.
- Very large projects may render slower.
- Prefer unique layer names for clarity in the diagram.