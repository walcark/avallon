# Bonjour 👋

Ceci est ma première page rendue depuis du **Markdown**, pensée pour
l'**écriture scientifique** : équations, code et figures.

## Équations

En ligne, la relation d'Einstein $E = mc^2$ s'insère dans le texte. En bloc :

$$
\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}
\qquad
\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}
$$

## Code

```python
import numpy as np

def softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    z = x - x.max()
    e = np.exp(z)
    return e / e.sum()
```

Et du code en ligne : `#!python np.exp(z)`.

## Figure

![Une fonction f(x) échantillonnée](/static/pages/img/demo-plot.svg)

## Encadrés

!!! note
    Les blocs `note` servent à mettre en avant une remarque.

!!! warning
    Et les blocs `warning` à signaler un point d'attention.

## Notations

Formule chimique H~2~O, exposant x^2^, et une note de bas de page.[^1]

[^1]: Les notes de bas de page sont gérées par l'extension `footnotes`.

## Tableau

| Nom | Description | URL |
| -- | -- | -- |
| Kevin | Le développeur de ce site web | www.ici.com |
