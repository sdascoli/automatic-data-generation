import pickle

import torch
import torchtext
from torchtext.data import BucketIterator
from automatic_data_generation.utils.utils import get_groups

class Datasets():
    def __init__(self, train_path='train.csv', valid_path='validate.csv',
                 emb_dim=100, emb_type='glove', max_vocab_size=10000, max_sequence_length=16,
                 tokenizer='split', preprocess='none'):
        
        if tokenizer == 'spacy':
            import spacy
            my_tok = spacy.load('en')
            # my_tok.tokenizer.add_sp

            def tokenize(x):
                # return [tok.text for tok in my_tok.tokenizer(x)]
                return [tok.lemma_ for tok in my_tok.tokenizer(x)]

        elif tokenizer == 'nltk':
            from nltk import word_tokenize
            from nltk.stem import WordNetLemmatizer, PorterStemmer

            def tokenize(x):
                if preprocess == 'stem':
                    stemmer = PorterStemmer()
                    return [stemmer.stem(tok) for tok in word_tokenize(x)]
                elif preprocess == 'lemmatize':
                    lemmatizer = WordNetLemmatizer()
                    return [lemmatizer.lemmatize(tok) for tok in
                            word_tokenize(x)]
                elif preprocess == 'none':
                    return word_tokenize(x)

        elif tokenizer == 'split':

            def tokenize(x):
                return x.split(" ")

        else:
            raise ValueError("Unknown tokenizer")

        self.tokenize = tokenize

        TEXT = torchtext.data.Field(lower=True, tokenize=self.tokenize,
                                    sequential=True, batch_first=True,
                                    include_lengths=True,
                                    fix_length=max_sequence_length,
                                    init_token='<sos>', eos_token='<eos>')
        LABEL = torchtext.data.Field(lower=False, tokenize=self.tokenize,
                                    sequential=True, batch_first=True,
                                    include_lengths=True,
                                    fix_length=max_sequence_length,
                                    init_token='<sos>', eos_token='<eos>')
        DELEX = torchtext.data.Field(lower=True, tokenize=self.tokenize,
                                     sequential=True, batch_first=True,
                                     include_lengths=True,
                                     fix_length=max_sequence_length,
                                     init_token='<sos>', eos_token='<eos>')
        INTENT = torchtext.data.Field(sequential=False, batch_first=True,
                                      unk_token=None, pad_token=None)

        skip_header = True
        if 'snips' in train_path:
            datafields = [("utterance", TEXT), ("labels", LABEL),
                          ("delexicalised", DELEX), ("intent", INTENT)]
        elif 'atis' in train_path:
            datafields = [(" ", None), ("utterance", TEXT), (" ", None),
                          ("intent", INTENT)]
        elif 'sentiment' in train_path:
            datafields = [("intent", INTENT), ("", None), ("", None),
                          ("", None), ("", None), ("utterance", TEXT)]
        elif 'yelp' in train_path:
            datafields = [("", None), ("", None), ("", None),
                          ("intent", INTENT), ("", None), ("utterance", TEXT),
                          ("", None), ("", None), ("", None)]
        elif 'spam' in train_path:
            datafields = [("utterance", TEXT), ("intent", INTENT)]
        elif 'bank' in train_path:
            datafields = [("utterance", TEXT)]
            skip_header = False
        else:
            raise ValueError("Unkown dataset")

        train, valid = torchtext.data.TabularDataset.splits(
            path='.',  # the root directory where the data lies
            train=train_path,
            validation=valid_path,
            format='csv',
            skip_header=skip_header,
            # if your csv header has a header, make sure to pass this to
            # ensure it doesn't get proceesed as data!
            fields=datafields
        )

        if emb_type == 'glove':
            emb_vectors = "glove.6B.{}d".format(emb_dim)
            TEXT.build_vocab(train, max_size=max_vocab_size, vectors=emb_vectors)
            DELEX.build_vocab(train, max_size=max_vocab_size, vectors=emb_vectors)
        elif emb_type == 'none':
            TEXT.build_vocab(train, max_size=max_vocab_size)
            DELEX.build_vocab(train, max_size=max_vocab_size)
            TEXT.vocab.vectors = torch.randn(len(TEXT.vocab.itos), emb_dim)
            DELEX.vocab.vectors = torch.randn(len(DELEX.vocab.itos), emb_dim)
        else:
            raise NotImplementedError

        LABEL.build_vocab(train)
        INTENT.build_vocab(train)

        self.emb_dim = emb_dim
        self.train = train
        self.valid = valid
        self.TEXT = TEXT
        self.DELEX = DELEX
        self.INTENT = INTENT

    def embed_slots(self, averaging='micro',
                    slotdic_path='./data/snips/train_slot_values.pkl'):
        """
        Create embeddings for the slots
        """

        if averaging == 'none':
            return

        with open(slotdic_path, 'rb') as f:
            slotdic = pickle.load(f)

        for i, token in enumerate(self.DELEX.vocab.itos):
            if token.startswith("_") and token.endswith("_"):
                slot = token.lstrip('_').rstrip('_')
                new_vectors = []

                slot_values = slotdic[slot]

                if averaging == 'micro':
                    for slot_value in slot_values:
                        for word in self.tokenize(slot_value):
                            if self.TEXT.vocab.stoi[word] != '<unk>':
                                new_vectors.append(self.TEXT.vocab.vectors[
                                                       self.TEXT.vocab.stoi[
                                                           word]])
                    new_vector = torch.mean(torch.stack(new_vectors))

                elif averaging == 'macro':
                    for slot_value in slot_values:
                        tmp = []
                        for word in self.tokenize(slot_value):
                            if self.TEXT.vocab.stoi[word] != '<unk>':
                                tmp.append(self.TEXT.vocab.vectors[
                                               self.TEXT.vocab.stoi[word]])
                        new_vectors.append(torch.mean(torch.stack(tmp)))
                    new_vector = torch.mean(torch.stack(new_vectors))

                else:
                    raise ValueError("Unknwon averaging strategy")

                self.DELEX.vocab.vectors[
                    self.DELEX.vocab.stoi[token]] = new_vector

    def get_iterators(self, batch_size=64):
        # make iterator for splits
        train_iter, valid_iter = BucketIterator.splits(
            (self.train, self.valid),
            # we pass in the datasets we want the iterator to draw data from
            batch_sizes=(batch_size, batch_size),
            device='cpu',
            # if you want to use the GPU, specify the GPU number here
            sort_key=lambda x: len(x.utterance),
            # the BucketIterator needs to be told what function it should
            # use to group the data.
            sort_within_batch=False,
            repeat=False,
            # we pass repeat=False because we want to wrap this Iterator layer.
        )

        return train_iter, valid_iter

    def embed_unks(self, vocab, init="randn", num_special_toks=2):
        emb_vectors = vocab.vectors
        sweep_range = len(vocab)
        running_norm = 0.
        num_non_zero = 0
        total_words = 0
        for i in range(num_special_toks, sweep_range):
            if len(emb_vectors[i].nonzero()) == 0:
                # std = 0.05 is based on the norm of average GloVE 100-dim
                # word vectors
                if init == "randn":
                    torch.nn.init.normal_(emb_vectors[i], mean=0, std=0.05)
            else:
                num_non_zero += 1
                running_norm += torch.norm(emb_vectors[i])
            total_words += 1
        print(
            "average GloVE norm is {}, number of known words are {}, "
            "total number of words are {}"
            .format(running_norm / num_non_zero, num_non_zero, total_words)
        )

    def get_slotdic(self):

        slotdic = {}
        encountered_slot_values = {}
    
        for example in list(self.train):

            utterance, labelling, delexicalised, intent = example.utterance, example.labels, example.delexicalised, example.intent
            groups = get_groups(utterance, labelling)
            for group in groups:
                if 'slot_name' in group.keys():
                    slot_name = group['slot_name']
                    slot_value = group['text']
                    if slot_name not in encountered_slot_values.keys():
                        encountered_slot_values[slot_name] = []
                    if slot_name not in slotdic.keys():
                        slotdic[slot_name] = []
                    if slot_value not in encountered_slot_values[slot_name]:
                        slotdic[slot_name].append(slot_value)
                    encountered_slot_values[slot_name].append(slot_value)

        return slotdic
