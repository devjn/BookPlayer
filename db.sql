create table progress(
    book_title text not null PRIMARY KEY,
    elapsed float not null,
    part int not null
);

create table currentbook(
    book_title text PRIMARY KEY
);
